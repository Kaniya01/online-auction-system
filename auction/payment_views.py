import hashlib
import hmac
import json
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Auction, Bid, Payment, PaymentAttempt, PaymentWebhookEvent
from .notifications import notify_user

logger = logging.getLogger(__name__)


def payment_configuration_available():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET and settings.RAZORPAY_WEBHOOK_SECRET)


def _client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise RuntimeError('Razorpay payment configuration is unavailable.')
    import razorpay
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def _winner_bid(auction):
    return Bid.objects.filter(auction=auction).select_related('buyer').order_by('-amount', '-bid_time').first()


def _amount_paise(amount):
    amount = Decimal(amount).quantize(Decimal('0.01'))
    return int((amount * 100).quantize(Decimal('1')))


@login_required
def my_payments(request):
    payments = Payment.objects.filter(buyer=request.user).select_related('auction__product').prefetch_related('attempts')
    return render(request, 'payments/my_payments.html', {'payments': payments, 'payment_configured': payment_configuration_available()})


@login_required
def payment_detail(request, auction_id):
    auction = get_object_or_404(Auction.objects.select_related('product', 'highest_bidder'), pk=auction_id)
    bid = _winner_bid(auction)
    if auction.status not in ('CLOSED', 'COMPLETED') or auction.highest_bidder_id != request.user.id or not bid or bid.buyer_id != request.user.id:
        return HttpResponse('Only the recorded winning bidder may view this payment.', status=403)
    payment = Payment.objects.filter(auction=auction, buyer=request.user).first()
    latest_attempt = payment.attempts.first() if payment else None
    return render(request, 'payments/payment_detail.html', {
        'auction': auction,
        'winning_bid': bid,
        'payment': payment,
        'latest_attempt': latest_attempt,
        'payment_configured': payment_configuration_available(),
        'currency': settings.RAZORPAY_CURRENCY,
    })


@login_required
@require_POST
def initiate_payment(request, auction_id):
    if not payment_configuration_available():
        return JsonResponse({'error': 'Online payment is temporarily unavailable. Please try again later.'}, status=503)
    if settings.RAZORPAY_CURRENCY != 'INR':
        return JsonResponse({'error': 'This checkout currently supports INR payments only.'}, status=503)

    # Persist a unique obligation and an attempt before making the provider
    # call. A concurrent request sees CREATING and cannot create another order.
    try:
        with transaction.atomic():
            auction = Auction.objects.select_for_update().select_related('product').get(pk=auction_id)
            winning_bid = _winner_bid(auction)
            if auction.status not in ('CLOSED', 'COMPLETED') or auction.status == 'CANCELLED':
                return JsonResponse({'error': 'Payment is available only after a non-cancelled auction has ended.'}, status=409)
            if not winning_bid or auction.highest_bidder_id != request.user.id or winning_bid.buyer_id != request.user.id:
                return JsonResponse({'error': 'Only the winning bidder can initiate this payment.'}, status=403)

            obligation, _ = Payment.objects.get_or_create(
                auction=auction,
                defaults={
                    'buyer': request.user,
                    'amount': winning_bid.amount,
                    'payment_method': 'RAZORPAY',
                    'payment_status': 'UNPAID',
                    'currency': settings.RAZORPAY_CURRENCY,
                },
            )
            obligation = Payment.objects.select_for_update().get(pk=obligation.pk)
            if obligation.buyer_id != request.user.id or obligation.amount != winning_bid.amount:
                return JsonResponse({'error': 'The payment record does not match the current auction result.'}, status=409)
            if obligation.payment_status == 'PAID':
                return JsonResponse({'error': 'This auction has already been paid.'}, status=409)
            if obligation.payment_status == 'COMPLETED':
                return JsonResponse({'error': 'A legacy payment record requires staff review before another payment can be attempted.'}, status=409)

            active_attempt = obligation.attempts.filter(status__in=('CREATING', 'PENDING', 'AUTHORIZED')).first()
            if active_attempt:
                if active_attempt.status == 'PENDING' and active_attempt.razorpay_order_id:
                    obligation.razorpay_order_id = active_attempt.razorpay_order_id
                    obligation.payment_status = 'PENDING'
                    obligation.save(update_fields=['razorpay_order_id', 'payment_status', 'updated_at'])
                    return JsonResponse(_checkout_payload(obligation, active_attempt))
                return JsonResponse({'error': 'A checkout attempt is already being processed. Please wait and refresh.'}, status=409)

            attempt_number = (obligation.attempts.order_by('-attempt_number').values_list('attempt_number', flat=True).first() or 0) + 1
            previous_attempt = obligation.attempts.first()
            if previous_attempt and previous_attempt.status == 'FAILED' and obligation.razorpay_order_id:
                # Razorpay orders support repeat attempts. Reuse the obligation's
                # single provider order instead of leaving an older payable order
                # beside a new one that could both be captured.
                attempt = PaymentAttempt.objects.create(
                    payment=obligation,
                    attempt_number=attempt_number,
                    status='PENDING',
                    razorpay_order_id=obligation.razorpay_order_id,
                )
                obligation.payment_status = 'PENDING'
                obligation.save(update_fields=['payment_status', 'updated_at'])
                return JsonResponse(_checkout_payload(obligation, attempt))
            attempt = PaymentAttempt.objects.create(payment=obligation, attempt_number=attempt_number, status='CREATING')
            obligation.payment_status = 'PENDING'
            obligation.save(update_fields=['payment_status', 'updated_at'])
    except Auction.DoesNotExist:
        return JsonResponse({'error': 'Auction not found.'}, status=404)
    except IntegrityError:
        return JsonResponse({'error': 'A payment attempt is already being created. Please retry shortly.'}, status=409)

    try:
        provider_order = _client().order.create(data={
            'amount': _amount_paise(winning_bid.amount),
            'currency': settings.RAZORPAY_CURRENCY,
            'receipt': f'auc-{auction.pk}',
            'notes': {'auction_id': str(auction.pk), 'payment_id': str(obligation.pk)},
        })
        provider_order_id = provider_order['id']
        if int(provider_order.get('amount', -1)) != _amount_paise(winning_bid.amount) or provider_order.get('currency') != settings.RAZORPAY_CURRENCY:
            raise ValueError('Razorpay returned an order with a mismatched amount or currency.')
        with transaction.atomic():
            locked_attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
            locked_payment = Payment.objects.select_for_update().get(pk=obligation.pk)
            locked_attempt.razorpay_order_id = provider_order_id
            locked_attempt.status = 'PENDING'
            locked_attempt.save(update_fields=['razorpay_order_id', 'status', 'updated_at'])
            locked_payment.razorpay_order_id = provider_order_id
            locked_payment.payment_status = 'PENDING'
            locked_payment.save(update_fields=['razorpay_order_id', 'payment_status', 'updated_at'])
        return JsonResponse(_checkout_payload(locked_payment, locked_attempt))
    except Exception as exc:
        logger.warning('Razorpay order creation failed for internal payment %s (%s)', obligation.pk, type(exc).__name__)
        PaymentAttempt.objects.filter(pk=attempt.pk).update(status='FAILED', failure_code=type(exc).__name__)
        Payment.objects.filter(pk=obligation.pk, payment_status='PENDING').update(payment_status='FAILED')
        return JsonResponse({'error': 'Could not start checkout. You can safely retry.'}, status=502)


def _checkout_payload(payment, attempt):
    return {
        'key': settings.RAZORPAY_KEY_ID,
        'order_id': attempt.razorpay_order_id,
        'amount': _amount_paise(payment.amount),
        'currency': payment.currency,
        'name': 'AuctionHub',
        'description': payment.auction.product.name,
        'verify_url': reverse('verify_checkout', args=[payment.auction_id]),
    }


@login_required
@require_POST
def verify_checkout(request, auction_id):
    try:
        data = json.loads(request.body or b'{}')
        order_id = str(data.get('razorpay_order_id', ''))
        payment_id = str(data.get('razorpay_payment_id', ''))
        signature = str(data.get('razorpay_signature', ''))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid verification request.'}, status=400)
    attempt = PaymentAttempt.objects.filter(
        payment__auction_id=auction_id,
        payment__buyer=request.user,
        razorpay_order_id=order_id,
    ).select_related('payment__auction__product', 'payment__buyer').order_by('-attempt_number').first()
    if attempt is None:
        return JsonResponse({'error': 'Payment order not found.'}, status=404)
    if data.get('failed') is True and payment_id:
        try:
            failed_payment = _client().payment.fetch(payment_id)
            _validate_provider_payment(attempt, failed_payment, payment_id)
            if failed_payment.get('status') == 'failed':
                if attempt.payment.payment_status != 'PAID':
                    PaymentAttempt.objects.filter(pk=attempt.pk).exclude(status='CAPTURED').update(
                        status='FAILED', razorpay_payment_id=payment_id,
                        failure_code=str(failed_payment.get('error_code') or '')[:100],
                    )
                    Payment.objects.filter(pk=attempt.payment_id).exclude(payment_status='PAID').update(payment_status='FAILED')
                return JsonResponse({'status': 'FAILED', 'message': 'The payment failed. You can safely retry.'})
        except Exception as exc:
            logger.info('Provider failure status check failed for attempt %s (%s)', attempt.pk, type(exc).__name__)
        return JsonResponse({'error': 'Payment failure is awaiting provider confirmation.'}, status=202)
    if not payment_id or not signature:
        return JsonResponse({'error': 'Missing payment verification details.'}, status=400)
    if attempt.status == 'CAPTURED' and attempt.razorpay_payment_id == payment_id:
        return JsonResponse({'status': 'PAID', 'message': 'Payment already verified.'})
    try:
        client = _client()
        client.utility.verify_payment_signature({
            'razorpay_order_id': attempt.razorpay_order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature,
        })
        provider_payment = client.payment.fetch(payment_id)
        _validate_provider_payment(attempt, provider_payment, payment_id)
    except Exception as exc:
        # Signature/API exceptions are deliberately not reflected to clients.
        logger.info('Payment verification rejected for attempt %s (%s)', attempt.pk, type(exc).__name__)
        return JsonResponse({'error': 'Payment could not be verified yet. Please refresh the payment page.'}, status=400)
    if provider_payment.get('status') == 'authorized':
        PaymentAttempt.objects.filter(pk=attempt.pk).exclude(status='CAPTURED').update(status='AUTHORIZED', razorpay_payment_id=payment_id)
        return JsonResponse({'status': 'AUTHORIZED', 'message': 'Payment is authorized and awaiting capture.'}, status=202)
    if provider_payment.get('status') != 'captured':
        return JsonResponse({'status': provider_payment.get('status', 'UNKNOWN'), 'message': 'Payment is not captured.'}, status=202)
    _mark_captured(attempt, payment_id)
    return JsonResponse({'status': 'PAID', 'message': 'Payment verified successfully.'})


def _validate_provider_payment(attempt, provider_payment, payment_id):
    payment = attempt.payment
    if provider_payment.get('id') != payment_id:
        raise ValueError('Payment ID mismatch')
    if provider_payment.get('order_id') != attempt.razorpay_order_id:
        raise ValueError('Order ID mismatch')
    if int(provider_payment.get('amount', -1)) != _amount_paise(payment.amount):
        raise ValueError('Amount mismatch')
    if provider_payment.get('currency') != payment.currency:
        raise ValueError('Currency mismatch')


@transaction.atomic
def _mark_captured(attempt, payment_id):
    locked_attempt = PaymentAttempt.objects.select_for_update().select_related('payment').get(pk=attempt.pk)
    payment = Payment.objects.select_for_update().get(pk=locked_attempt.payment_id)
    if payment.payment_status == 'PAID':
        if payment.razorpay_payment_id != payment_id:
            raise ValueError('Payment obligation already captured with a different payment.')
        return
    now = timezone.now()
    locked_attempt.razorpay_payment_id = payment_id
    locked_attempt.status = 'CAPTURED'
    locked_attempt.save(update_fields=['razorpay_payment_id', 'status', 'updated_at'])
    payment.razorpay_order_id = locked_attempt.razorpay_order_id
    payment.razorpay_payment_id = payment_id
    payment.transaction_reference = payment_id
    payment.payment_method = 'RAZORPAY'
    payment.payment_status = 'PAID'
    payment.paid_at = now
    payment.save(update_fields=['razorpay_order_id', 'razorpay_payment_id', 'transaction_reference', 'payment_method', 'payment_status', 'paid_at', 'updated_at'])
    notify_user(
        payment.buyer,
        notification_type='PAYMENT',
        title=f"Payment confirmed for {payment.auction.product.name}",
        message=f"Your Razorpay payment of ₹{payment.amount} was captured.",
        event_key=f'auction-payment-captured-{payment.auction_id}',
        link_url=f'/payments/{payment.auction_id}/',
    )


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    signature = request.headers.get('X-Razorpay-Signature', '')
    event_id = request.headers.get('X-Razorpay-Event-Id', '')
    if not secret or not event_id or len(event_id) > 128 or not signature:
        return HttpResponse(status=400)
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return HttpResponse(status=400)
    try:
        payload = json.loads(request.body)
        event_type = payload.get('event', '')
        if not isinstance(event_type, str) or len(event_type) > 80:
            return HttpResponse(status=400)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)

    processing_error = None
    try:
        with transaction.atomic():
            event, created = PaymentWebhookEvent.objects.select_for_update().get_or_create(
                event_id=event_id,
                defaults={'event_type': event_type, 'status': 'RECEIVED'},
            )
            if not created and event.status == 'PROCESSED':
                return HttpResponse(status=200)
            event.event_type = event_type
            event.status = 'PROCESSING'
            event.error_message = ''
            event.save(update_fields=['event_type', 'status', 'error_message'])
            try:
                _process_webhook_payload(event, payload)
            except Exception as exc:
                event.status = 'FAILED'
                event.error_message = type(exc).__name__[:240]
                event.save(update_fields=['status', 'error_message'])
                processing_error = exc
            else:
                event.status = 'PROCESSED'
                event.processed_at = timezone.now()
                event.save(update_fields=['status', 'processed_at'])
    except Exception as exc:
        logger.error('Razorpay webhook processing failed (%s)', type(exc).__name__)
        PaymentWebhookEvent.objects.filter(event_id=event_id).update(status='FAILED', error_message=type(exc).__name__[:240])
        return HttpResponse(status=500)
    if processing_error:
        logger.error('Razorpay webhook event could not be applied (%s)', type(processing_error).__name__)
        return HttpResponse(status=500)
    return HttpResponse(status=200)


def _process_webhook_payload(event, payload):
    event_type = event.event_type
    if event_type not in ('payment.captured', 'payment.failed', 'order.paid'):
        return
    entity = payload.get('payload', {}).get('payment', {}).get('entity') or {}
    if not entity and event_type == 'order.paid':
        entity = payload.get('payload', {}).get('order', {}).get('entity') or {}
    order_id = entity.get('order_id') or (entity.get('id') if entity.get('entity') == 'order' else '')
    payment_id = entity.get('id') if entity.get('entity') == 'payment' else ''
    # Some order.paid payloads contain only the order object. That event is
    # acknowledged and stored, but cannot establish a captured payment without
    # a payment entity to validate. The payment.captured event or verified
    # Checkout callback supplies that authoritative payment record.
    if event_type == 'order.paid' and not payment_id:
        return
    attempt = None
    if payment_id:
        attempt = PaymentAttempt.objects.select_related('payment').filter(razorpay_payment_id=payment_id).first()
    if not attempt and order_id:
        attempt = PaymentAttempt.objects.select_related('payment').filter(razorpay_order_id=order_id).order_by('-attempt_number').first()
    if not attempt:
        # Durable event receipt is still useful; no local order is affected.
        return
    event.attempt = attempt
    event.save(update_fields=['attempt'])
    if event_type in ('payment.captured', 'order.paid'):
        _validate_provider_payment(attempt, entity, payment_id)
        if entity.get('status') not in ('captured', 'paid'):
            raise ValueError('Provider event does not report a captured payment.')
        _mark_captured(attempt, payment_id)
    elif event_type == 'payment.failed':
        with transaction.atomic():
            locked_attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
            payment = Payment.objects.select_for_update().get(pk=locked_attempt.payment_id)
            if payment.payment_status != 'PAID':
                locked_attempt.razorpay_payment_id = payment_id or None
                locked_attempt.status = 'FAILED'
                locked_attempt.failure_code = str(entity.get('error_code') or '')[:100]
                locked_attempt.save(update_fields=['razorpay_payment_id', 'status', 'failure_code', 'updated_at'])
                payment.payment_status = 'FAILED'
                payment.save(update_fields=['payment_status', 'updated_at'])

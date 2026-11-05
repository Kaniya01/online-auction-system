import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Auction, Payment


@login_required
def make_payment(request, auction_id):
    auction = get_object_or_404(
        Auction.objects.select_related(
            'product',
            'highest_bidder'
        ),
        id=auction_id
    )

    # Only the winner of a closed auction can pay.
    if (
        auction.status not in ['CLOSED', 'COMPLETED']
        or auction.highest_bidder_id != request.user.id
    ):
        messages.error(
            request,
            'You are not eligible to pay for this auction.'
        )
        return redirect('dashboard')

    # A payment already exists for this auction.
    existing_payment = Payment.objects.filter(
        auction=auction
    ).first()

    if existing_payment:
        return render(
            request,
            'payment_result.html',
            {'payment': existing_payment}
        )

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', '').strip()

        valid_methods = dict(Payment.PAYMENT_METHOD_CHOICES)

        if payment_method not in valid_methods:
            messages.error(request, 'Please select a valid payment method.')
            return redirect('make_payment', auction_id=auction.id)

        with transaction.atomic():
            # Recheck inside the transaction to avoid duplicate payments.
            payment, created = Payment.objects.get_or_create(
                auction=auction,
                defaults={
                    'buyer': request.user,
                    'amount': auction.current_highest_bid,
                    'payment_method': payment_method,
                    'payment_status': 'COMPLETED',
                    'transaction_reference': f'DEMO-{uuid.uuid4().hex[:20].upper()}',
                }
            )

        if created:
            messages.success(
                request,
                'Demo payment recorded successfully.'
            )

        return redirect('my_payments')

    return render(
        request,
        'make_payment.html',
        {'auction': auction}
    )


@login_required
def my_payments(request):
    payments = Payment.objects.filter(
        buyer=request.user
    ).select_related(
        'auction',
        'auction__product'
    ).order_by('-payment_date')

    return render(
        request,
        'my_payments.html',
        {'payments': payments}
    )
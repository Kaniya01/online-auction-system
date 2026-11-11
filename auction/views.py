from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.views import PasswordChangeView, PasswordResetView
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Exists, Max, OuterRef, Prefetch, Subquery, Sum
from django.db.models.functions import TruncDate
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from .forms import RegistrationForm, ProfileForm, ProductForm, AuctionForm, SafePasswordResetForm
from .models import Profile, Product, Auction, ProductImage, Bid, Notification, Payment, PaymentAttempt
from .browse_views import update_auction_status
from .notifications import notify_user


# =========================================================
# REGISTER
# =========================================================

def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            full_name = form.cleaned_data['full_name']
            phone_number = form.cleaned_data['phone_number']

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            Profile.objects.update_or_create(
                user=user,
                defaults={
                    'full_name': full_name,
                    'phone_number': phone_number,
                },
            )
            Notification.objects.create(
                user=user,
                title='Welcome to AuctionHub',
                message='Your account is ready. Browse auctions or list a product to get started.',
                notification_type='REGISTRATION',
            )

            messages.success(
                request,
                'Account created successfully! You can now log in.',
                extra_tags='registration',
            )
            return redirect('login')
    else:
        form = RegistrationForm()

    return render(request, 'register.html', {'form': form})


# =========================================================
# LOGIN
# =========================================================

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('dashboard')

        messages.error(
            request,
            'Invalid username or password.',
            extra_tags='login',
        )

    return render(request, 'login.html')


# =========================================================
# DASHBOARD
# =========================================================

@login_required
def dashboard(request):
    user = request.user

    # Current dashboard mode
    mode = request.session.get('mode', 'BUYER')

    # -----------------------------------------------------
    # SELLER DATA
    # -----------------------------------------------------

    my_products = Product.objects.filter(
        seller=user
    ).order_by('-created_at')

    my_auctions = Auction.objects.filter(
        product__seller=user
    ).select_related(
        'product'
    ).order_by('-created_at')

    # -----------------------------------------------------
    # BUYER AUCTIONS
    # -----------------------------------------------------

    my_bid_auctions = list(
        Auction.objects.filter(
            bids__buyer=user
        ).select_related(
            'product',
            'product__seller'
        ).prefetch_related(
            'bids'
        ).distinct().order_by('-end_time')
    )

    # Refresh auction status and highest bid information
    for auction in my_bid_auctions:
        update_auction_status(auction)

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            auction.current_highest_bid = highest_bid.amount
            auction.highest_bidder = highest_bid.buyer

            auction.save(
                update_fields=[
                    'current_highest_bid',
                    'highest_bidder'
                ]
            )
        elif auction.current_highest_bid is None:
            auction.current_highest_bid = auction.starting_bid
            auction.save(update_fields=['current_highest_bid'])

    # Remove duplicate auctions
    unique_auctions = {
        auction.id: auction for auction in my_bid_auctions
    }
    my_bid_auctions = list(unique_auctions.values())

    # -----------------------------------------------------
    # ACTIVE BIDS
    # -----------------------------------------------------

    active_bids = [
        auction
        for auction in my_bid_auctions
        if auction.status == 'ACTIVE'
    ]

    # -----------------------------------------------------
    # WON AUCTIONS
    # -----------------------------------------------------

    won_auctions = [
        auction
        for auction in my_bid_auctions
        if (
            auction.status in ['CLOSED', 'COMPLETED']
            and auction.highest_bidder_id == user.id
        )
    ]
    payment_records = Payment.objects.filter(
        auction_id__in=[auction.pk for auction in won_auctions]
    ).in_bulk(field_name='auction_id')
    for auction in won_auctions:
        auction.payment_record = payment_records.get(auction.pk)

    # -----------------------------------------------------
    # AUCTIONS ENDING SOON
    # -----------------------------------------------------

    ending_auctions = Auction.objects.filter(
        status='ACTIVE'
    ).exclude(
        product__seller=user
    ).select_related(
        'product'
    ).order_by('end_time')[:5]

    for auction in ending_auctions:
        update_auction_status(auction)

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            auction.current_highest_bid = highest_bid.amount
            auction.highest_bidder = highest_bid.buyer

            auction.save(
                update_fields=[
                    'current_highest_bid',
                    'highest_bidder'
                ]
            )

    context = {
        'user': user,
        'mode': mode,

        # Seller information
        'my_products_count': my_products.count(),
        'my_auctions_count': my_auctions.count(),
        'my_products': my_products,
        'my_auctions': my_auctions,

        # Buyer information
        'active_bids_count': len(active_bids),
        'won_auctions_count': len(won_auctions),
        'active_bids': active_bids,
        'won_auctions': won_auctions,
        'ending_auctions': ending_auctions,
        'unread_notification_count': Notification.objects.filter(
            user=user,
            is_read=False,
        ).count(),
    }

    return render(request, 'dashboard.html', context)


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user).order_by('-created_at')
    page = Paginator(items, 20).get_page(request.GET.get('page'))
    return render(request, 'notifications.html', {'notifications': page})


class SafePasswordResetView(PasswordResetView):
    form_class = SafePasswordResetForm
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    subject_template_name = 'registration/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')

    def form_valid(self, form):
        messages.success(self.request, 'If an account matches that email, password reset instructions have been sent.')
        return super().form_valid(form)


class SafePasswordChangeView(PasswordChangeView):
    template_name = 'registration/password_change_form.html'
    success_url = reverse_lazy('password_change_done')

    def form_valid(self, form):
        messages.success(self.request, 'Your password has been changed.')
        return super().form_valid(form)


@login_required
def mark_notification_read(request, notification_id):
    if request.method == 'POST':
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user,
        )
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
    return redirect('notifications')


@login_required
def mark_all_notifications_read(request):
    if request.method == 'POST':
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect('notifications')


# =========================================================
# SELLER AUCTIONS
# =========================================================

@login_required
def seller_auctions(request):
    bid_exists = Bid.objects.filter(auction_id=OuterRef('pk'))
    payment_exists = Payment.objects.filter(auction_id=OuterRef('pk'))
    attempt_exists = PaymentAttempt.objects.filter(payment__auction_id=OuterRef('pk'))
    auctions = Auction.objects.filter(
        product__seller=request.user
    ).select_related(
        'product'
    ).annotate(
        has_bids=Exists(bid_exists),
        has_payment=Exists(payment_exists),
        has_payment_attempts=Exists(attempt_exists),
    ).order_by('-created_at')

    # Refresh open auctions without changing cancelled/completed history.
    for auction in auctions:
        update_auction_status(auction)
        auction.can_edit_schedule = (
            auction.status == 'SCHEDULED'
            and auction.start_time > timezone.now()
            and auction.end_time > timezone.now()
            and not auction.has_bids
            and not auction.has_payment
            and not auction.has_payment_attempts
        )

    selected_status = request.GET.get('status', '').upper()
    valid_statuses = {key for key, _ in Auction.STATUS_CHOICES}
    if selected_status in valid_statuses:
        auctions = auctions.filter(status=selected_status)

    return render(
        request,
        'seller_auctions.html',
        {
            'auctions': auctions,
            'selected_status': selected_status if selected_status in valid_statuses else '',
            'status_choices': Auction.STATUS_CHOICES,
        }
    )


@login_required
def received_bids(request):
    seller_auctions = Auction.objects.filter(
        product__seller=request.user,
    ).select_related('product').prefetch_related('product__images')
    for auction in seller_auctions:
        update_auction_status(auction)

    status = request.GET.get('status', '').upper()
    valid_statuses = {key for key, _ in Auction.STATUS_CHOICES}
    if status not in valid_statuses:
        status = ''

    auction_id = request.GET.get('auction', '')
    allowed_ids = set(seller_auctions.values_list('pk', flat=True))
    selected_auction = None
    if auction_id.isdigit() and int(auction_id) in allowed_ids:
        selected_auction = int(auction_id)
    else:
        auction_id = ''

    bids = Bid.objects.filter(
        auction__product__seller=request.user,
    ).select_related(
        'buyer', 'auction', 'auction__product',
    ).prefetch_related(
        'auction__product__images',
        Prefetch(
            'auction__bids',
            queryset=Bid.objects.select_related('buyer').order_by('-amount', '-bid_time'),
            to_attr='ranked_bids',
        ),
    ).order_by('-bid_time')
    if status:
        bids = bids.filter(auction__status=status)
    if selected_auction:
        bids = bids.filter(auction_id=selected_auction)

    page_obj = Paginator(bids, 25).get_page(request.GET.get('page'))
    leading_ids = {}
    for bid in page_obj.object_list:
        if bid.auction_id not in leading_ids:
            leading = bid.auction.ranked_bids[0] if bid.auction.ranked_bids else None
            leading_ids[bid.auction_id] = leading.pk if leading else None
        bid.is_leading = leading_ids[bid.auction_id] == bid.pk

    return render(request, 'received_bids.html', {
        'page_obj': page_obj,
        'bids': page_obj.object_list,
        'auctions': seller_auctions,
        'status_choices': Auction.STATUS_CHOICES,
        'selected_status': status,
        'selected_auction': str(selected_auction or ''),
    })


@login_required
def seller_winners(request):
    refreshable = Auction.objects.filter(
        product__seller=request.user,
    ).exclude(status__in=('COMPLETED', 'CANCELLED')).select_related('product')
    for auction in refreshable:
        update_auction_status(auction)

    auctions = Auction.objects.filter(
        product__seller=request.user,
        status__in=('CLOSED', 'COMPLETED'),
    ).select_related(
        'product', 'highest_bidder',
    ).prefetch_related(
        'product__images',
        Prefetch(
            'bids',
            queryset=Bid.objects.select_related('buyer').order_by('-amount', '-bid_time'),
            to_attr='ranked_bids',
        ),
    ).order_by('-end_time')

    winner_rows = []
    payment_records = Payment.objects.filter(
        auction_id__in=[auction.pk for auction in auctions]
    ).in_bulk(field_name='auction_id')
    for auction in auctions:
        winning_bid = auction.ranked_bids[0] if auction.ranked_bids else None
        payment = payment_records.get(auction.pk)
        if payment and payment.payment_status == 'PAID':
            payment_label = 'Paid'
        elif payment and payment.payment_status == 'PENDING':
            payment_label = 'Pending'
        elif payment and payment.payment_status == 'FAILED':
            payment_label = 'Failed'
        elif payment and payment.payment_status == 'COMPLETED':
            payment_label = 'Legacy record · unverified'
        else:
            payment_label = 'Unpaid'
        winner_rows.append({'auction': auction, 'winning_bid': winning_bid, 'payment_label': payment_label})

    return render(request, 'seller_winners.html', {'winner_rows': winner_rows})


@login_required
def seller_analytics(request):
    seller_auctions = Auction.objects.filter(product__seller=request.user)
    refreshable = seller_auctions.exclude(status__in=('COMPLETED', 'CANCELLED')).select_related('product')
    for auction in refreshable:
        update_auction_status(auction)

    seller_auctions = Auction.objects.filter(product__seller=request.user)
    status_totals = dict(
        seller_auctions.values('status').annotate(total=Count('pk')).values_list('status', 'total')
    )
    total_auctions = sum(status_totals.values())
    status_chart = []
    for key, label in Auction.STATUS_CHOICES:
        count = status_totals.get(key, 0)
        status_chart.append({
            'label': label,
            'count': count,
            'percent': round(count * 100 / total_auctions) if total_auctions else 0,
        })

    winning_bid_id = Subquery(
        Bid.objects.filter(auction_id=OuterRef('auction_id'))
        .order_by('-amount', '-bid_time')
        .values('pk')[:1]
    )
    winning_bids = Bid.objects.filter(
        auction__product__seller=request.user,
        auction__status__in=('CLOSED', 'COMPLETED'),
        pk=winning_bid_id,
    )
    win_metrics = winning_bids.aggregate(
        total=Sum('amount'),
        highest=Max('amount'),
        average=Avg('amount'),
    )

    bid_days = list(
        Bid.objects.filter(auction__product__seller=request.user)
        .annotate(day=TruncDate('bid_time'))
        .values('day').annotate(total=Count('pk')).order_by('-day')[:14]
    )
    max_daily_bids = max((row['total'] for row in bid_days), default=0)
    bid_chart = [
        {
            'day': row['day'],
            'count': row['total'],
            'percent': round(row['total'] * 100 / max_daily_bids) if max_daily_bids else 0,
        }
        for row in reversed(bid_days)
    ]

    recent_activity = []
    recent_bids = Bid.objects.filter(
        auction__product__seller=request.user,
    ).select_related('auction__product').order_by('-bid_time')[:8]
    for bid in recent_bids:
        recent_activity.append({
            'created_at': bid.bid_time,
            'text': f'Bid received on {bid.auction.product.name}: ₹{bid.amount}',
            'url': reverse('auction_detail', args=[bid.auction_id]),
        })
    recent_auctions = seller_auctions.select_related('product').order_by('-created_at')[:8]
    for auction in recent_auctions:
        recent_activity.append({
            'created_at': auction.created_at,
            'text': f'Auction listed: {auction.product.name}',
            'url': reverse('auction_detail', args=[auction.pk]),
        })
    recent_activity.sort(key=lambda item: item['created_at'], reverse=True)

    context = {
        'total_products': Product.objects.filter(seller=request.user).count(),
        'active_auctions': status_totals.get('ACTIVE', 0),
        'scheduled_auctions': status_totals.get('SCHEDULED', 0),
        'completed_auctions': status_totals.get('COMPLETED', 0),
        'cancelled_auctions': status_totals.get('CANCELLED', 0),
        'closed_auctions': status_totals.get('CLOSED', 0),
        'auctions_with_bids': seller_auctions.filter(bids__isnull=False).distinct().count(),
        'auctions_without_bids': seller_auctions.filter(bids__isnull=True).count(),
        'total_bids': Bid.objects.filter(auction__product__seller=request.user).count(),
        'winning_bid_value': win_metrics['total'] or 0,
        'highest_winning_bid': win_metrics['highest'] or 0,
        'average_winning_bid': win_metrics['average'] or 0,
        'status_chart': status_chart,
        'bid_chart': bid_chart,
        'recent_activity': recent_activity[:10],
    }
    return render(request, 'seller_analytics.html', context)


@login_required
def manage_product(request, product_id):
    if request.method != 'POST':
        return redirect('seller_products')

    with transaction.atomic():
        product = get_object_or_404(
            Product.objects.select_for_update(),
            pk=product_id,
            seller=request.user,
        )
        has_auction = Auction.objects.filter(product=product).exists()
        if has_auction:
            product.is_archived = not product.is_archived
            product.save(update_fields=['is_archived'])
            message = 'Product archived. Its auction history remains available.' if product.is_archived else 'Product restored.'
        else:
            product.delete()
            message = 'Unused product deleted.'
    messages.success(request, message)
    return redirect('seller_products')


@login_required
def cancel_auction(request, auction_id):
    auction = get_object_or_404(
        Auction.objects.select_related('product'),
        pk=auction_id,
        product__seller=request.user,
    )
    update_auction_status(auction)
    if auction.status not in ('SCHEDULED', 'ACTIVE'):
        messages.error(request, 'Only scheduled or active auctions can be cancelled.')
        return redirect('seller_auctions')

    if request.method != 'POST':
        return render(request, 'confirm_cancel_auction.html', {'auction': auction})

    with transaction.atomic():
        auction = get_object_or_404(
            Auction.objects.select_for_update().select_related('product'),
            pk=auction_id,
            product__seller=request.user,
        )
        update_auction_status(auction)
        if auction.status not in ('SCHEDULED', 'ACTIVE'):
            messages.error(request, 'This auction is no longer eligible for cancellation.')
            return redirect('seller_auctions')

        bidder_ids = list(auction.bids.order_by().values_list('buyer_id', flat=True).distinct())
        auction.status = 'CANCELLED'
        auction.save(update_fields=['status'])
        bidders = get_user_model().objects.filter(pk__in=bidder_ids)
        for bidder in bidders:
            notify_user(
                bidder,
                title=f'Auction cancelled: {auction.product.name}',
                message=f'The seller cancelled the auction for {auction.product.name}. Existing bids remain in the auction history.',
                notification_type='AUCTION_CANCELLED',
                event_key=f'auction-cancelled-{auction.pk}-{bidder.pk}',
                link_url=reverse('auction_detail', args=[auction.pk]),
            )

    messages.success(request, 'Auction cancelled. Bids and history have been preserved, and bidders have been notified.')
    return redirect('seller_auctions')


# =========================================================
# SWITCH BUYER / SELLER MODE
# =========================================================

@login_required
def switch_mode(request, mode):
    mode = mode.upper()

    if mode in ['BUYER', 'SELLER']:
        request.session['mode'] = mode

    return redirect('dashboard')


# =========================================================
# LOGOUT
# =========================================================

def logout_view(request):
    logout(request)
    messages.success(
        request,
        'You have been logged out.',
        extra_tags='logout',
    )
    return redirect('login')


FAQ_ITEMS = [
    {'category': 'Buyer guide', 'question': 'How do I browse auctions?', 'answer': 'Open Browse Auctions, use search or category filters, then open a listing for its current status and bid history.'},
    {'category': 'Buyer guide', 'question': 'How do I save an auction?', 'answer': 'Use the watchlist control on an eligible scheduled or active auction. Saved auctions remain visible after they end.'},
    {'category': 'Placing bids', 'question': 'How do bids work?', 'answer': 'A bid must be greater than the current highest bid, use no more than two decimal places, and be placed while the auction is active. Bids cannot be withdrawn through the site.'},
    {'category': 'Creating auctions', 'question': 'How do I create an auction?', 'answer': 'Switch to Seller mode, add a product, and create a future auction schedule for that product. Archived products cannot be listed.'},
    {'category': 'Seller guide', 'question': 'Can I manage products after listing?', 'answer': 'Unused products can be deleted. Products with auction history are archived so their listing and bid history are preserved.'},
    {'category': 'Auction closing and winners', 'question': 'What happens when an auction closes?', 'answer': 'The highest valid bid at closing is recorded as the winner. Cancelled auctions remain distinct and do not have winners.'},
    {'category': 'Auction closing and winners', 'question': 'How do I pay for an auction I won?', 'answer': 'The recorded winning bidder can open Payment details from the dashboard and use Razorpay Checkout when payment configuration is available. A payment is shown as paid only after server verification confirms capture; an authorized payment is not yet captured.'},
    {'category': 'Account and security', 'question': 'How do I reset my password?', 'answer': 'Use Forgot password on the login page. A time-limited link is sent to the email address on your account.'},
    {'category': 'General platform questions', 'question': 'How do I report a suspicious listing?', 'answer': 'Open the auction and submit one report with a reason and optional details. Authorized staff review reports in the admin area.'},
]


def help_faq(request):
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    items = FAQ_ITEMS
    if category:
        items = [item for item in items if item['category'] == category]
    if query:
        needle = query.casefold()
        items = [item for item in items if needle in item['question'].casefold() or needle in item['answer'].casefold()]
    categories = sorted({item['category'] for item in FAQ_ITEMS})
    return render(request, 'help_faq.html', {'faqs': items, 'categories': categories, 'query': query, 'selected_category': category})


def terms_and_conditions(request):
    return render(request, 'terms.html')


def privacy_policy(request):
    return render(request, 'privacy.html')


def auction_rules(request):
    return render(request, 'auction_rules.html')


# =========================================================
# PROFILE
# =========================================================

@login_required
def profile(request):
    user_profile = request.user.profile

    return render(
        request,
        'profile.html',
        {
            'profile': user_profile,
            'user': request.user,
        }
    )


# =========================================================
# EDIT PROFILE
# =========================================================

@login_required
def edit_profile(request):
    user_profile = request.user.profile

    if request.method == 'POST':
        form = ProfileForm(
            request.POST,
            request.FILES,
            instance=user_profile
        )

        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('dashboard')
    else:
        form = ProfileForm(instance=user_profile)

    return render(
        request,
        'edit_profile.html',
        {
            'form': form,
            'profile': user_profile,
        }
    )


# =========================================================
# ADD PRODUCT
# =========================================================

@login_required
def add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)

        if form.is_valid():
            product = form.save(commit=False)
            product.seller = request.user
            product.save()

            # Save all uploaded product images
            images = request.FILES.getlist('images')

            for image in images:
                ProductImage.objects.create(
                    product=product,
                    image=image
                )

            messages.success(request, 'Product added successfully!')

            return redirect(
                'create_auction',
                product_id=product.id
            )
    else:
        form = ProductForm()

    return render(
        request,
        'add_product.html',
        {'form': form}
    )


# =========================================================
# EDIT PRODUCT
# =========================================================

@login_required
def edit_product(request, product_id):
    product = get_object_or_404(
        Product,
        id=product_id,
        seller=request.user
    )

    if request.method == 'POST':
        form = ProductForm(
            request.POST,
            request.FILES,
            instance=product
        )

        if form.is_valid():
            form.save()

            # Add any newly uploaded images
            images = request.FILES.getlist('images')

            for image in images:
                ProductImage.objects.create(
                    product=product,
                    image=image
                )

            messages.success(request, 'Product updated successfully!')
            return redirect('seller_products')
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        'edit_product.html',
        {
            'form': form,
            'product': product,
        }
    )


# =========================================================
# DELETE PRODUCT IMAGE
# =========================================================

@login_required
def delete_product_image(request, image_id):
    image = get_object_or_404(
        ProductImage,
        id=image_id,
        product__seller=request.user
    )

    product_id = image.product.id

    if request.method == 'POST':
        image.image.delete(save=False)
        image.delete()

        messages.success(
            request,
            'Product image removed successfully.'
        )

    return redirect('edit_product', product_id=product_id)


# =========================================================
# CREATE AUCTION
# =========================================================

@login_required
def create_auction(request, product_id):
    product = get_object_or_404(
        Product,
        id=product_id,
        seller=request.user
    )

    if product.is_archived:
        messages.error(request, 'Archived products cannot be used to create an auction.')
        return redirect('seller_products')

    if request.method == 'POST':
        form = AuctionForm(request.POST)

        if form.is_valid():
            auction = form.save(commit=False)
            auction.product = product
            auction.starting_bid = product.starting_price
            auction.current_highest_bid = product.starting_price
            auction.status = 'SCHEDULED'
            auction.save()

            Notification.objects.create(
                user=request.user,
                title=f"Auction created: {product.name}",
                message='Your auction is scheduled and will open at the selected start time.',
                notification_type='AUCTION_CREATED',
            )

            messages.success(request, 'Auction created successfully!')
            return redirect('dashboard')
    else:
        form = AuctionForm()

    return render(
        request,
        'create_auction.html',
        {
            'form': form,
            'product': product,
        }
    )


# =========================================================
# EDIT AUCTION
# =========================================================

@login_required
def edit_auction(request, auction_id):
    def eligibility_error(locked_auction):
        # Run the clock-based transition while holding the auction row lock.
        # This makes the scheduled-state decision agree with bidding and payment
        # requests, which also lock the auction before changing related records.
        update_auction_status(locked_auction)
        if locked_auction.status == 'CANCELLED':
            return 'Cancelled auctions cannot be edited.'
        if locked_auction.status in ('CLOSED', 'COMPLETED'):
            return 'Ended or completed auctions cannot be edited.'
        if timezone.now() >= locked_auction.start_time:
            return 'This auction has already started and cannot be edited.'
        if timezone.now() >= locked_auction.end_time:
            return 'This auction has already ended and cannot be edited.'
        if locked_auction.status != 'SCHEDULED':
            return 'Only scheduled auctions can be edited.'
        if Bid.objects.filter(auction=locked_auction).exists():
            return 'Auctions with bid history cannot be edited.'
        if Payment.objects.filter(auction=locked_auction).exists() or PaymentAttempt.objects.filter(
            payment__auction=locked_auction,
        ).exists():
            return 'Auctions with payment records cannot be edited.'
        return ''

    if request.method == 'POST':
        with transaction.atomic():
            auction = get_object_or_404(
                Auction.objects.select_for_update().select_related('product'),
                id=auction_id,
                product__seller=request.user,
            )
            block_reason = eligibility_error(auction)
            if block_reason:
                messages.error(request, block_reason)
                return redirect('seller_auctions')

            form = AuctionForm(request.POST, instance=auction)
            if form.is_valid():
                updated_auction = form.save(commit=False)
                # Change only the two requested schedule fields. Keep all auction
                # summary, ownership, winner, status, and history data untouched.
                auction.start_time = updated_auction.start_time
                auction.end_time = updated_auction.end_time
                auction.save(update_fields=['start_time', 'end_time'])
                messages.success(request, 'Auction schedule updated successfully.')
                return redirect('seller_auctions')
    else:
        auction = get_object_or_404(
            Auction.objects.select_related('product'),
            id=auction_id,
            product__seller=request.user,
        )
        block_reason = eligibility_error(auction)
        if block_reason:
            messages.error(request, block_reason)
            return redirect('seller_auctions')
        form = AuctionForm(instance=auction)

    return render(
        request,
        'edit_auction.html',
        {
            'form': form,
            'auction': auction,
        }
    )


# =========================================================
# SELLER PRODUCTS
# =========================================================

@login_required
def seller_products(request):
    products = Product.objects.filter(
        seller=request.user
    ).select_related('auction').order_by('-created_at')

    return render(
        request,
        'seller_products.html',
        {'products': products}
    )

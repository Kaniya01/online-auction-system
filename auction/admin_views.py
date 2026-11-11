from functools import wraps
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .browse_views import update_auction_status
from .models import Auction, AuctionReport, Bid, Product, Profile
from .notifications import notify_user


def staff_admin_required(view_func):
    """Protect custom admin views independently of navigation visibility."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse('login'))
        if not request.user.is_active or not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped


@staff_admin_required
def dashboard(request):
    activity = []
    for user in User.objects.order_by('-date_joined').only('pk', 'username', 'date_joined')[:8]:
        activity.append({'at': user.date_joined, 'title': 'User registered', 'detail': user.username, 'url': reverse('staff_admin_user_detail', args=[user.pk])})
    for auction in Auction.objects.select_related('product').order_by('-created_at')[:8]:
        activity.append({'at': auction.created_at, 'title': 'Auction listed', 'detail': auction.product.name, 'url': reverse('staff_admin_auction_detail', args=[auction.pk])})
    for bid in Bid.objects.select_related('buyer', 'auction__product').order_by('-bid_time')[:8]:
        activity.append({'at': bid.bid_time, 'title': 'Bid placed', 'detail': f'{bid.buyer.username} · ₹{bid.amount} · {bid.auction.product.name}', 'url': reverse('staff_admin_auction_detail', args=[bid.auction_id])})
    for report in AuctionReport.objects.select_related('auction__product').order_by('-created_at')[:8]:
        activity.append({'at': report.created_at, 'title': 'Listing reported', 'detail': report.auction.product.name, 'url': reverse('staff_admin_report_detail', args=[report.pk])})
    activity.sort(key=lambda item: item['at'], reverse=True)
    return render(request, 'admin/admin_dashboard.html', {
        'total_users': User.objects.count(),
        'active_users': User.objects.filter(is_active=True).count(),
        'buyer_profiles': Profile.objects.filter(role='BUYER').count(),
        'seller_profiles': Profile.objects.filter(role='SELLER').count(),
        'total_products': Product.objects.count(),
        'total_auctions': Auction.objects.count(),
        'active_auctions': Auction.objects.filter(status='ACTIVE').count(),
        'scheduled_auctions': Auction.objects.filter(status='SCHEDULED').count(),
        'completed_auctions': Auction.objects.filter(status__in=('CLOSED', 'COMPLETED')).count(),
        'cancelled_auctions': Auction.objects.filter(status='CANCELLED').count(),
        'pending_reports': AuctionReport.objects.filter(status='OPEN').count(),
        'recent_activity': activity[:15],
    })


@staff_admin_required
def user_list(request):
    users = User.objects.all().order_by('-date_joined')
    query = request.GET.get('q', '').strip()
    active = request.GET.get('active', '')
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    if active in ('active', 'inactive'):
        users = users.filter(is_active=(active == 'active'))
    page = Paginator(users, 25).get_page(request.GET.get('page'))
    return render(request, 'admin/user_list.html', {'users': page, 'query': query, 'active_filter': active})


@staff_admin_required
def user_detail(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    return render(request, 'admin/user_detail.html', {
        'target_user': target,
        'profile': Profile.objects.filter(user=target).first(),
        'recent_bids': Bid.objects.filter(buyer=target).select_related('auction__product').order_by('-bid_time')[:10],
        'products': Product.objects.filter(seller=target).order_by('-created_at')[:10],
        'reports': AuctionReport.objects.filter(reporter=target).count(),
    })


@staff_admin_required
def set_user_active(request, user_id):
    if request.method != 'POST':
        return redirect('staff_admin_user_detail', user_id=user_id)
    target = get_object_or_404(User, pk=user_id)
    action = request.POST.get('action')
    if action not in ('activate', 'deactivate'):
        messages.error(request, 'Choose a valid account action.')
    elif action == 'deactivate' and target.pk == request.user.pk:
        messages.error(request, 'You cannot deactivate your own account.')
    elif action == 'deactivate' and target.is_superuser:
        messages.error(request, 'Superuser accounts cannot be deactivated here.')
    else:
        target.is_active = action == 'activate'
        target.save(update_fields=['is_active'])
        messages.success(request, f'Account {"activated" if target.is_active else "deactivated"}.')
    return redirect('staff_admin_user_detail', user_id=target.pk)


@staff_admin_required
def product_list(request):
    products = Product.objects.select_related('seller').prefetch_related('images').order_by('-created_at')
    query = request.GET.get('q', '').strip()
    seller = request.GET.get('seller', '').strip()
    archived = request.GET.get('archived', '')
    if query:
        products = products.filter(name__icontains=query)
    if seller.isdigit():
        products = products.filter(seller_id=int(seller))
    if archived in ('yes', 'no'):
        products = products.filter(is_archived=(archived == 'yes'))
    page = Paginator(products, 25).get_page(request.GET.get('page'))
    return render(request, 'admin/product_list.html', {
        'products': page, 'query': query, 'seller_filter': seller, 'archived_filter': archived,
        'sellers': User.objects.filter(products__isnull=False).distinct().order_by('username'),
    })


@staff_admin_required
def product_detail(request, product_id):
    product = get_object_or_404(Product.objects.select_related('seller').prefetch_related('images'), pk=product_id)
    return render(request, 'admin/product_detail.html', {'product': product, 'auction': Auction.objects.filter(product=product).first()})


@staff_admin_required
def toggle_product_archive(request, product_id):
    if request.method != 'POST':
        return redirect('staff_admin_product_detail', product_id=product_id)
    with transaction.atomic():
        product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
        product.is_archived = not product.is_archived
        product.save(update_fields=['is_archived'])
    messages.success(request, f'Product {"archived" if product.is_archived else "restored"}; auction history was preserved.')
    return redirect('staff_admin_product_detail', product_id=product.pk)


@staff_admin_required
def auction_list(request):
    auctions = Auction.objects.select_related('product', 'product__seller').order_by('-created_at')
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').upper()
    seller = request.GET.get('seller', '').strip()
    if query:
        auctions = auctions.filter(product__name__icontains=query)
    if status in {key for key, _ in Auction.STATUS_CHOICES}:
        auctions = auctions.filter(status=status)
    else:
        status = ''
    if seller.isdigit():
        auctions = auctions.filter(product__seller_id=int(seller))
    page = Paginator(auctions, 25).get_page(request.GET.get('page'))
    return render(request, 'admin/auction_list.html', {
        'auctions': page, 'query': query, 'selected_status': status, 'seller_filter': seller,
        'status_choices': Auction.STATUS_CHOICES,
        'sellers': User.objects.filter(products__auction__isnull=False).distinct().order_by('username'),
    })


@staff_admin_required
def auction_detail(request, auction_id):
    auction = get_object_or_404(Auction.objects.select_related('product__seller', 'highest_bidder').prefetch_related('bids__buyer'), pk=auction_id)
    bids = auction.bids.select_related('buyer').order_by('-amount', '-bid_time')
    participants = User.objects.filter(bids__auction=auction).distinct().order_by('username')
    return render(request, 'admin/auction_detail.html', {'auction': auction, 'bids': bids, 'participants': participants})


@staff_admin_required
def cancel_auction(request, auction_id):
    if request.method != 'POST':
        auction = get_object_or_404(Auction.objects.select_related('product'), pk=auction_id)
        update_auction_status(auction)
        if auction.status not in ('SCHEDULED', 'ACTIVE'):
            messages.error(request, 'Only scheduled or active auctions can be cancelled.')
            return redirect('staff_admin_auction_detail', auction_id=auction.pk)
        return render(request, 'admin/confirm_cancel_auction.html', {'auction': auction})
    with transaction.atomic():
        auction = get_object_or_404(Auction.objects.select_for_update().select_related('product'), pk=auction_id)
        update_auction_status(auction)
        if auction.status not in ('SCHEDULED', 'ACTIVE'):
            messages.error(request, 'This auction is no longer eligible for cancellation.')
        else:
            bidder_ids = auction.bids.order_by().values_list('buyer_id', flat=True).distinct()
            auction.status = 'CANCELLED'
            auction.save(update_fields=['status'])
            for bidder in User.objects.filter(pk__in=bidder_ids):
                notify_user(
                    bidder, title=f'Auction cancelled: {auction.product.name}',
                    message='An administrator cancelled this auction. Existing bids and history remain available.',
                    notification_type='AUCTION_CANCELLED', event_key=f'auction-cancelled-{auction.pk}-{bidder.pk}',
                    link_url=reverse('auction_detail', args=[auction.pk]),
                )
            messages.success(request, 'Auction cancelled; bids and history were preserved.')
    return redirect('staff_admin_auction_detail', auction_id=auction.pk)


@staff_admin_required
def report_list(request):
    reports = AuctionReport.objects.select_related('auction__product__seller', 'reporter').order_by('-created_at')
    status = request.GET.get('status', '').upper()
    query = request.GET.get('q', '').strip()
    if status in {'OPEN', 'REVIEWED', 'DISMISSED'}:
        reports = reports.filter(status=status)
    else:
        status = ''
    if query:
        reports = reports.filter(Q(auction__product__name__icontains=query) | Q(reporter__username__icontains=query) | Q(description__icontains=query))
    page = Paginator(reports, 25).get_page(request.GET.get('page'))
    return render(request, 'admin/report_list.html', {'reports': page, 'selected_status': status, 'query': query})


@staff_admin_required
def report_detail(request, report_id):
    report = get_object_or_404(AuctionReport.objects.select_related('auction__product__seller', 'reporter'), pk=report_id)
    return render(request, 'admin/report_detail.html', {'report': report})


@staff_admin_required
def review_report(request, report_id):
    if request.method != 'POST':
        return redirect('staff_admin_report_detail', report_id=report_id)
    report = get_object_or_404(AuctionReport, pk=report_id)
    action = request.POST.get('action')
    note = request.POST.get('admin_note', '').strip()
    if action not in ('reviewed', 'dismissed'):
        messages.error(request, 'Choose a valid report resolution.')
    elif len(note) > 2000:
        messages.error(request, 'Administrative notes must be 2000 characters or fewer.')
    else:
        report.status = action.upper()
        report.admin_note = note
        report.reviewed_at = timezone.now()
        report.save(update_fields=['status', 'admin_note', 'reviewed_at'])
        messages.success(request, 'Report resolution saved.')
    return redirect('staff_admin_report_detail', report_id=report.pk)


@staff_admin_required
def platform_reports(request):
    auction_status = {row['status']: row['total'] for row in Auction.objects.values('status').annotate(total=Count('pk'))}
    report_status = {row['status']: row['total'] for row in AuctionReport.objects.values('status').annotate(total=Count('pk'))}
    bid_summary = Bid.objects.aggregate(
        total=Count('pk'),
        last_30_days=Count('pk', filter=Q(bid_time__gte=timezone.now() - timedelta(days=30))),
    )
    return render(request, 'admin/platform_reports.html', {
        'registrations': User.objects.count(), 'active_users': User.objects.filter(is_active=True).count(),
        'products': Product.objects.aggregate(total=Count('pk'), archived=Count('pk', filter=Q(is_archived=True))),
        'auctions': Auction.objects.count(), 'auction_status': auction_status,
        'bids': bid_summary, 'average_bid': Bid.objects.aggregate(value=Avg('amount'))['value'],
        'reports': AuctionReport.objects.count(), 'report_status': report_status,
    })


@staff_admin_required
def platform_analytics(request):
    registrations = list(
        User.objects.annotate(month=TruncMonth('date_joined'))
        .values('month').annotate(total=Count('pk')).order_by('-month')[:6]
    )
    bids_by_day = list(
        Bid.objects.annotate(day=TruncDate('bid_time'))
        .values('day').annotate(total=Count('pk')).order_by('-day')[:14]
    )
    categories = list(
        Product.objects.values('category').annotate(total=Count('pk'))
        .order_by('-total', 'category')[:10]
    )
    return render(request, 'admin/platform_analytics.html', {
        'registrations_by_month': registrations,
        'bids_by_day': bids_by_day,
        'products_by_category': categories,
        'active_auctions': Auction.objects.filter(status='ACTIVE').count(),
        'scheduled_auctions': Auction.objects.filter(status='SCHEDULED').count(),
    })

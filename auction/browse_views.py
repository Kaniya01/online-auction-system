from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Auction, Bid, Notification


# =========================================================
# AUCTION STATUS
# =========================================================

@transaction.atomic
def update_auction_status(auction):
    """
    Update auction status based on the current time.

    Also makes sure the current highest bid and winning bidder
    are synchronized with the actual Bid records.
    """

    # Lock the row so competing requests cannot repeat a transition or notify
    # the winner more than once.
    locked_auction = Auction.objects.select_for_update().select_related(
        'product'
    ).get(pk=auction.pk)

    # A completed auction is an administrative/business decision and must not
    # be changed back to CLOSED just because its end time has passed.
    if locked_auction.status == 'COMPLETED':
        auction.status = locked_auction.status
        auction.current_highest_bid = locked_auction.current_highest_bid
        auction.highest_bidder = locked_auction.highest_bidder
        return auction

    previous_status = locked_auction.status
    now = timezone.now()

    # -----------------------------------------------------
    # SCHEDULED
    # -----------------------------------------------------

    if now < locked_auction.start_time:

        new_status = 'SCHEDULED'

        highest_bid = locked_auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            new_highest_bid = highest_bid.amount
            new_highest_bidder = highest_bid.buyer
        else:
            new_highest_bid = locked_auction.starting_bid
            new_highest_bidder = None

    # -----------------------------------------------------
    # ACTIVE
    # -----------------------------------------------------

    elif locked_auction.start_time <= now < locked_auction.end_time:

        new_status = 'ACTIVE'

        highest_bid = locked_auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            new_highest_bid = highest_bid.amount
            new_highest_bidder = highest_bid.buyer
        else:
            new_highest_bid = locked_auction.starting_bid
            new_highest_bidder = None

    # -----------------------------------------------------
    # CLOSED
    # -----------------------------------------------------

    else:

        new_status = 'CLOSED'

        highest_bid = locked_auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            new_highest_bid = highest_bid.amount
            new_highest_bidder = highest_bid.buyer
        else:
            new_highest_bid = locked_auction.starting_bid
            new_highest_bidder = None

    # -----------------------------------------------------
    # UPDATE AUCTION
    # -----------------------------------------------------

    locked_auction.status = new_status
    locked_auction.current_highest_bid = new_highest_bid
    locked_auction.highest_bidder = new_highest_bidder

    locked_auction.save(
        update_fields=[
            'status',
            'current_highest_bid',
            'highest_bidder'
        ]
    )

    if new_status == 'CLOSED' and previous_status != 'CLOSED' and new_highest_bidder:
        Notification.objects.create(
            user=new_highest_bidder,
            notification_type='WINNER',
            title=f"You won {auction.product.name}",
            message=(
                f"The auction for {locked_auction.product.name} has ended. "
                f"Your winning bid was ₹{new_highest_bid}."
            ),
        )

    auction.status = locked_auction.status
    auction.current_highest_bid = locked_auction.current_highest_bid
    auction.highest_bidder = locked_auction.highest_bidder

    return auction


# =========================================================
# BROWSE AUCTIONS
# =========================================================

@login_required
def browse_auctions(request):

    auctions = Auction.objects.select_related(
        'product',
        'product__seller'
    ).prefetch_related(
        'product__images'
    ).order_by('end_time')

    # Refresh statuses before displaying auctions.
    for auction in auctions:
        update_auction_status(auction)

    # Search
    search_query = request.GET.get('q', '').strip()

    if search_query:
        auctions = auctions.filter(
            Q(product__name__icontains=search_query) |
            Q(product__category__icontains=search_query) |
            Q(product__description__icontains=search_query)
        )

    # Category filter
    category = request.GET.get('category', '').strip()

    if category:
        auctions = auctions.filter(
            product__category=category
        )

    # Available categories
    # Include categories from all auctions because closed
    # auctions are also displayed.
    categories = Auction.objects.values_list(
        'product__category',
        flat=True
    ).distinct().order_by('product__category')

    context = {
        'auctions': auctions,
        'categories': categories,
        'search_query': search_query,
        'selected_category': category,
    }

    return render(
        request,
        'browse_auctions.html',
        context
    )


# =========================================================
# AUCTION DETAILS
# =========================================================

@login_required
def auction_detail(request, auction_id):

    auction = get_object_or_404(
        Auction.objects.select_related(
            'product',
            'product__seller'
        ).prefetch_related(
            'product__images',
            'bids__buyer'
        ),
        id=auction_id
    )

    # Refresh auction status.
    auction = update_auction_status(auction)

    # Latest bid placed by the current buyer.
    my_bid = auction.bids.filter(
        buyer=request.user
    ).order_by(
        '-amount',
        '-bid_time'
    ).first()

    context = {
        'auction': auction,
        'my_bid': my_bid,
    }

    return render(
        request,
        'auction_detail.html',
        context
    )


# =========================================================
# PLACE BID
# =========================================================

@login_required
def place_bid(request, auction_id):
    if request.method != 'POST':
        return redirect('auction_detail', auction_id=auction_id)

    def reject(message):
        messages.error(request, message)
        return redirect('auction_detail', auction_id=auction_id)

    # Keep the lock until both the bid and its auction summary are saved.
    with transaction.atomic():
        auction = get_object_or_404(
            Auction.objects.select_for_update().select_related('product'),
            id=auction_id
        )
        update_auction_status(auction)

        if auction.product.seller_id == request.user.id:
            response = reject('You cannot bid on your own auction.')
        elif auction.status != 'ACTIVE':
            response = reject({
                'SCHEDULED': 'This auction has not started yet.',
                'CLOSED': 'This auction has already ended.',
            }.get(auction.status, 'Bidding is not available for this auction.'))
        else:
            try:
                amount = Decimal(request.POST.get('amount', '').strip())
            except (InvalidOperation, ValueError):
                amount = None

            valid_amount = (
                amount is not None
                and amount.is_finite()
                and amount > auction.current_highest_bid
                and amount.as_tuple().exponent >= -2
                and len(amount.as_tuple().digits) <= 12
                and amount.adjusted() < 10
            )
            if not valid_amount:
                response = reject(
                    f'Enter a valid bid greater than ₹{auction.current_highest_bid} '
                    'with at most two decimal places.'
                )
            else:
                previous_highest_bidder = auction.highest_bidder
                Bid.objects.create(auction=auction, buyer=request.user, amount=amount)
                auction.current_highest_bid = amount
                auction.highest_bidder = request.user
                auction.save(update_fields=['current_highest_bid', 'highest_bidder'])
                if previous_highest_bidder and previous_highest_bidder != request.user:
                    Notification.objects.create(
                        user=previous_highest_bidder,
                        title=f"You were outbid on {auction.product.name}",
                        message=f"A new bid of ₹{amount} was placed on {auction.product.name}.",
                        notification_type='OUTBID',
                    )
                Notification.objects.create(
                    user=auction.product.seller,
                    title=f"New bid on {auction.product.name}",
                    message=f"{request.user.username} bid ₹{amount} on your auction.",
                    notification_type='BID',
                )
                response = None

    if response:
        return response

    messages.success(
        request,
        f'Your bid of ₹{amount} was placed successfully!'
    )

    return redirect(
        'auction_detail',
        auction_id=auction.id
    )


# =========================================================
# MY BIDS
# =========================================================

@login_required
def my_bids(request):

    # Get all auctions where the current user has bid.
    auctions = Auction.objects.filter(
        bids__buyer=request.user
    ).select_related(
        'product',
        'product__seller'
    ).prefetch_related(
        'bids'
    ).distinct().order_by(
        '-end_time'
    )

    # Refresh auction status.
    for auction in auctions:
        update_auction_status(auction)

    # Prepare one record per auction.
    bid_data = []

    for auction in auctions:

        # Get the user's latest/highest bid for this auction.
        my_bid = auction.bids.filter(
            buyer=request.user
        ).order_by(
            '-amount',
            '-bid_time'
        ).first()

        # Determine whether the user is currently winning.
        is_highest_bidder = (
            auction.highest_bidder_id == request.user.id
        )

        bid_data.append({
            'auction': auction,
            'my_bid': my_bid,
            'is_highest_bidder': is_highest_bidder,
        })

    context = {
        'bid_data': bid_data,
    }

    return render(
        request,
        'my_bids.html',
        context
    )

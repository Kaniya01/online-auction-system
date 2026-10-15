from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Auction, Bid


# =========================================================
# AUCTION STATUS
# =========================================================

def update_auction_status(auction):
    """
    Update auction status based on the current time.

    Also makes sure the current highest bid and winning bidder
    are synchronized with the actual Bid records.
    """

    now = timezone.now()

    # -----------------------------------------------------
    # SCHEDULED
    # -----------------------------------------------------

    if now < auction.start_time:

        new_status = 'SCHEDULED'

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            new_highest_bid = highest_bid.amount
            new_highest_bidder = highest_bid.buyer
        else:
            new_highest_bid = auction.starting_bid
            new_highest_bidder = None

    # -----------------------------------------------------
    # ACTIVE
    # -----------------------------------------------------

    elif auction.start_time <= now < auction.end_time:

        new_status = 'ACTIVE'

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            new_highest_bid = highest_bid.amount
            new_highest_bidder = highest_bid.buyer
        else:
            new_highest_bid = auction.starting_bid
            new_highest_bidder = None

    # -----------------------------------------------------
    # CLOSED
    # -----------------------------------------------------

    else:

        new_status = 'CLOSED'

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:
            new_highest_bid = highest_bid.amount
            new_highest_bidder = highest_bid.buyer
        else:
            new_highest_bid = auction.starting_bid
            new_highest_bidder = None

    # -----------------------------------------------------
    # UPDATE AUCTION
    # -----------------------------------------------------

    auction.status = new_status
    auction.current_highest_bid = new_highest_bid
    auction.highest_bidder = new_highest_bidder

    auction.save(
        update_fields=[
            'status',
            'current_highest_bid',
            'highest_bidder'
        ]
    )

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

    auction = get_object_or_404(
        Auction.objects.select_related(
            'product'
        ),
        id=auction_id
    )

    # Always refresh status before accepting a bid.
    auction = update_auction_status(auction)

    if request.method != 'POST':
        return redirect(
            'auction_detail',
            auction_id=auction.id
        )

    # Seller cannot bid on their own auction.
    if auction.product.seller_id == request.user.id:
        messages.error(
            request,
            'You cannot bid on your own auction.'
        )

        return redirect(
            'auction_detail',
            auction_id=auction.id
        )

    # Auction must be live.
    if auction.status != 'ACTIVE':

        if auction.status == 'SCHEDULED':
            messages.error(
                request,
                'This auction has not started yet.'
            )

        elif auction.status == 'CLOSED':
            messages.error(
                request,
                'This auction has already ended.'
            )

        else:
            messages.error(
                request,
                'Bidding is not available for this auction.'
            )

        return redirect(
            'auction_detail',
            auction_id=auction.id
        )

    # Get amount from form.
    amount_text = request.POST.get('amount', '').strip()

    if not amount_text:
        messages.error(
            request,
            'Please enter a bid amount.'
        )

        return redirect(
            'auction_detail',
            auction_id=auction.id
        )

    # Convert amount safely.
    try:
        amount = Decimal(amount_text)
    except (InvalidOperation, ValueError):
        messages.error(
            request,
            'Please enter a valid bid amount.'
        )

        return redirect(
            'auction_detail',
            auction_id=auction.id
        )

    # Bid must be greater than current highest bid.
    if amount <= auction.current_highest_bid:
        messages.error(
            request,
            f'Your bid must be greater than ₹{auction.current_highest_bid}.'
        )

        return redirect(
            'auction_detail',
            auction_id=auction.id
        )

    # Create bid.
    Bid.objects.create(
        auction=auction,
        buyer=request.user,
        amount=amount
    )

    # Update highest bid.
    auction.current_highest_bid = amount
    auction.highest_bidder = request.user

    auction.save(
        update_fields=[
            'current_highest_bid',
            'highest_bidder'
        ]
    )

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
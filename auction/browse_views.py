from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.db.models import Q

from .models import Auction


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
    ).exclude(
        status__in=['CLOSED', 'COMPLETED']
    ).order_by('end_time')

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
    categories = Auction.objects.exclude(
        status__in=['CLOSED', 'COMPLETED']
    ).values_list(
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
            'product__images'
        ),
        id=auction_id
    )

    context = {
        'auction': auction,
    }

    return render(
        request,
        'auction_detail.html',
        context
    )
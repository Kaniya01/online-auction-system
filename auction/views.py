from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import (
    RegistrationForm,
    ProfileForm,
    ProductForm,
    AuctionForm,
)
from .models import Profile, Product, Auction, Bid
from .browse_views import update_auction_status


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

            # Create Django user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # Create corresponding profile
            Profile.objects.create(
                user=user,
                full_name=full_name,
                phone_number=phone_number
            )

            messages.success(
                request,
                'Account created successfully! You can now log in.'
            )

            return redirect('login')

    else:

        form = RegistrationForm()

    return render(
        request,
        'register.html',
        {
            'form': form
        }
    )


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

            return redirect('dashboard')

        messages.error(
            request,
            'Invalid username or password.'
        )

    return render(
        request,
        'login.html'
    )


# =========================================================
# UPDATE ALL AUCTION STATUSES
# =========================================================

def update_auction_statuses():

    """
    Automatically update auction status based on
    start_time and end_time.
    """

    now = timezone.now()

    auctions = Auction.objects.all()

    for auction in auctions:

        if now < auction.start_time:

            new_status = 'SCHEDULED'

        elif auction.start_time <= now < auction.end_time:

            new_status = 'ACTIVE'

        else:

            new_status = 'CLOSED'

        if auction.status != new_status:

            auction.status = new_status

            auction.save(
                update_fields=['status']
            )


# =========================================================
# DASHBOARD
# =========================================================

@login_required
def dashboard(request):

    """
    Main authenticated user dashboard.

    Every logged-in user can switch between:

    BUYER mode
    SELLER mode

    Buyer activity is calculated from actual Bid records.

    Auction status, current highest bid and highest bidder
    are refreshed before displaying the dashboard.
    """

    user = request.user


    # =====================================================
    # CURRENT MODE
    # =====================================================

    mode = request.session.get(
        'mode',
        'BUYER'
    )


    # =====================================================
    # SELLER DATA
    # =====================================================

    my_products = Product.objects.filter(
        seller=user
    ).order_by(
        '-created_at'
    )


    my_auctions = Auction.objects.filter(
        product__seller=user
    ).select_related(
        'product'
    ).order_by(
        '-created_at'
    )


    # =====================================================
    # BUYER AUCTIONS
    # =====================================================

    # Get every auction where this user has placed
    # at least one bid.

    my_bid_auctions = list(
        Auction.objects.filter(
            bids__buyer=user
        ).select_related(
            'product',
            'product__seller'
        ).prefetch_related(
            'bids'
        ).distinct().order_by(
            '-end_time'
        )
    )


    # =====================================================
    # REFRESH BUYER AUCTIONS
    # =====================================================

    for auction in my_bid_auctions:

        # -------------------------------------------------
        # Update SCHEDULED / ACTIVE / CLOSED
        # -------------------------------------------------

        update_auction_status(auction)


        # -------------------------------------------------
        # Find actual highest bid
        # -------------------------------------------------

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()


        if highest_bid:

            # Update current highest bid

            auction.current_highest_bid = (
                highest_bid.amount
            )

            # Update highest bidder

            auction.highest_bidder = (
                highest_bid.buyer
            )

            auction.save(
                update_fields=[
                    'current_highest_bid',
                    'highest_bidder'
                ]
            )

        else:

            # No bids yet.
            #
            # Keep the starting bid as the current
            # displayed value.

            if auction.current_highest_bid is None:

                auction.current_highest_bid = (
                    auction.starting_bid
                )

                auction.save(
                    update_fields=[
                        'current_highest_bid'
                    ]
                )


    # =====================================================
    # REMOVE DUPLICATE AUCTIONS
    # =====================================================

    unique_auctions = {}

    for auction in my_bid_auctions:

        unique_auctions[auction.id] = auction

    my_bid_auctions = list(
        unique_auctions.values()
    )


    # =====================================================
    # ACTIVE BIDS
    # =====================================================

    active_bids = [

        auction

        for auction in my_bid_auctions

        if auction.status == 'ACTIVE'
    ]


    # =====================================================
    # WON AUCTIONS
    # =====================================================

    won_auctions = [

        auction

        for auction in my_bid_auctions

        if (
            auction.status == 'CLOSED'
            and auction.highest_bidder_id == user.id
        )
    ]


    # =====================================================
    # COUNTS
    # =====================================================

    active_bids_count = len(
        active_bids
    )

    won_auctions_count = len(
        won_auctions
    )


    # =====================================================
    # AUCTIONS ENDING SOON
    # =====================================================

    ending_auctions = Auction.objects.filter(
        status='ACTIVE'
    ).exclude(
        product__seller=user
    ).select_related(
        'product'
    ).order_by(
        'end_time'
    )[:5]


    # =====================================================
    # REFRESH ENDING-SOON AUCTIONS
    # =====================================================

    for auction in ending_auctions:

        update_auction_status(auction)

        highest_bid = auction.bids.order_by(
            '-amount',
            '-bid_time'
        ).first()

        if highest_bid:

            auction.current_highest_bid = (
                highest_bid.amount
            )

            auction.highest_bidder = (
                highest_bid.buyer
            )

            auction.save(
                update_fields=[
                    'current_highest_bid',
                    'highest_bidder'
                ]
            )


    # =====================================================
    # CONTEXT
    # =====================================================

    context = {

        'user': user,


        # =================================================
        # CURRENT MODE
        # =================================================

        'mode': mode,


        # =================================================
        # SELLER
        # =================================================

        'my_products_count': my_products.count(),

        'my_auctions_count': my_auctions.count(),

        'my_products': my_products,

        'my_auctions': my_auctions,


        # =================================================
        # BUYER
        # =================================================

        'active_bids_count': active_bids_count,

        'won_auctions_count': won_auctions_count,

        'active_bids': active_bids,

        'won_auctions': won_auctions,

        'ending_auctions': ending_auctions,

    }


    return render(
        request,
        'dashboard.html',
        context
    )


# =========================================================
# SWITCH BUYER / SELLER MODE
# =========================================================

@login_required
def switch_mode(request, mode):

    """
    Switch the logged-in user's dashboard mode.

    Mode is stored in the session, not the database.
    """

    mode = mode.upper()

    if mode in [
        'BUYER',
        'SELLER'
    ]:

        request.session['mode'] = mode

    return redirect(
        'dashboard'
    )


# =========================================================
# LOGOUT
# =========================================================

def logout_view(request):

    logout(request)

    messages.success(
        request,
        'You have been logged out.'
    )

    return redirect(
        'login'
    )


# =========================================================
# PROFILE
# =========================================================

@login_required
def profile(request):

    profile = request.user.profile

    return render(
        request,
        'profile.html',
        {
            'profile': profile,
            'user': request.user,
        }
    )


# =========================================================
# EDIT PROFILE
# =========================================================

@login_required
def edit_profile(request):

    profile = request.user.profile

    if request.method == 'POST':

        form = ProfileForm(
            request.POST,
            request.FILES,
            instance=profile
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                'Profile updated successfully!'
            )

            return redirect(
                'dashboard'
            )

    else:

        form = ProfileForm(
            instance=profile
        )

    return render(
        request,
        'edit_profile.html',
        {
            'form': form,
            'profile': profile,
        }
    )


# =========================================================
# ADD PRODUCT
# =========================================================

@login_required
def add_product(request):

    # Only logged-in users can add products.
    # The seller is always the current user.

    if request.method == 'POST':

        form = ProductForm(
            request.POST
        )

        if form.is_valid():

            product = form.save(
                commit=False
            )

            product.seller = request.user

            product.save()

            messages.success(
                request,
                'Product added successfully!'
            )

            return redirect(
                'create_auction',
                product_id=product.id
            )

    else:

        form = ProductForm()

    return render(
        request,
        'add_product.html',
        {
            'form': form
        }
    )


# =========================================================
# EDIT PRODUCT
# =========================================================

@login_required
def edit_product(
    request,
    product_id
):

    product = Product.objects.get(
        id=product_id,
        seller=request.user
    )

    if request.method == 'POST':

        form = ProductForm(
            request.POST,
            instance=product
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                'Product updated successfully!'
            )

            return redirect(
                'seller_products'
            )

    else:

        form = ProductForm(
            instance=product
        )

    return render(
        request,
        'edit_product.html',
        {
            'form': form,
            'product': product,
        }
    )


# =========================================================
# CREATE AUCTION
# =========================================================

@login_required
def create_auction(
    request,
    product_id
):

    product = Product.objects.get(
        id=product_id,
        seller=request.user
    )

    if request.method == 'POST':

        form = AuctionForm(
            request.POST
        )

        if form.is_valid():

            auction = form.save(
                commit=False
            )

            auction.product = product

            auction.starting_bid = (
                product.starting_price
            )

            auction.current_highest_bid = (
                product.starting_price
            )

            auction.status = 'SCHEDULED'

            auction.save()

            messages.success(
                request,
                'Auction created successfully!'
            )

            return redirect(
                'dashboard'
            )

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
# SELLER PRODUCTS
# =========================================================

@login_required
def seller_products(request):

    products = Product.objects.filter(
        seller=request.user
    ).order_by(
        '-created_at'
    )

    return render(
        request,
        'seller_products.html',
        {
            'products': products,
        }
    )
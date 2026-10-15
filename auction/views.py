from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import RegistrationForm, ProfileForm, ProductForm, AuctionForm
from .models import Profile, Product, Auction, ProductImage, Bid
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

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

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
            return redirect('dashboard')

        messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')


# =========================================================
# UPDATE ALL AUCTION STATUSES
# =========================================================

def update_auction_statuses():
    """Update auction statuses according to their scheduled times."""
    now = timezone.now()

    for auction in Auction.objects.all():
        if now < auction.start_time:
            new_status = 'SCHEDULED'
        elif auction.start_time <= now < auction.end_time:
            new_status = 'ACTIVE'
        else:
            new_status = 'CLOSED'

        if auction.status != new_status:
            auction.status = new_status
            auction.save(update_fields=['status'])


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
            auction.status == 'CLOSED'
            and auction.highest_bidder_id == user.id
        )
    ]

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
    }

    return render(request, 'dashboard.html', context)


# =========================================================
# SELLER AUCTIONS
# =========================================================

@login_required
def seller_auctions(request):
    auctions = Auction.objects.filter(
        product__seller=request.user
    ).select_related(
        'product'
    ).order_by('-created_at')

    return render(
        request,
        'seller_auctions.html',
        {'auctions': auctions}
    )


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
    messages.success(request, 'You have been logged out.')
    return redirect('login')


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

    if request.method == 'POST':
        form = AuctionForm(request.POST)

        if form.is_valid():
            auction = form.save(commit=False)
            auction.product = product
            auction.starting_bid = product.starting_price
            auction.current_highest_bid = product.starting_price
            auction.status = 'SCHEDULED'
            auction.save()

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
    auction = get_object_or_404(
        Auction,
        id=auction_id,
        product__seller=request.user
    )

    # Auctions cannot be edited after their start time.
    if timezone.now() >= auction.start_time:
        messages.error(
            request,
            'This auction has already started and cannot be edited.'
        )
        return redirect('seller_auctions')

    if auction.status in ['ACTIVE', 'CLOSED', 'COMPLETED']:
        messages.error(
            request,
            'This auction can no longer be edited.'
        )
        return redirect('seller_auctions')

    if request.method == 'POST':
        form = AuctionForm(request.POST, instance=auction)

        if form.is_valid():
            updated_auction = form.save(commit=False)

            if updated_auction.start_time <= timezone.now():
                messages.error(
                    request,
                    'Auction start time must be in the future.'
                )
            else:
                updated_auction.status = 'SCHEDULED'
                updated_auction.save()

                messages.success(
                    request,
                    'Auction updated successfully!'
                )
                return redirect('seller_auctions')
    else:
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
    ).order_by('-created_at')

    return render(
        request,
        'seller_products.html',
        {'products': products}
    )
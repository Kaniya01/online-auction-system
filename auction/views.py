from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import RegistrationForm, ProfileForm, ProductForm, AuctionForm
from .models import Profile, Product, Auction

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

        # Invalid credentials
        messages.error(
            request,
            'Invalid username or password.'
        )

    return render(
        request,
        'login.html'
    )

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
            auction.save(update_fields=['status'])

# =========================================================
# DASHBOARD
# =========================================================
@login_required
def dashboard(request):
    """
    Main authenticated user dashboard.

    Every logged-in user can switch between:
    BUYER mode and SELLER mode.
    The selected mode is stored in the session,
    so no database changes are required.
    """
    update_auction_statuses()

    user = request.user

    # Get the current mode from the session.
    # New users start in Buyer mode.
    mode = request.session.get('mode', 'BUYER')

    # -----------------------------------------------------
    # SELLER DATA
    # -----------------------------------------------------

    my_products = Product.objects.filter(
        seller=request.user
    ).order_by('-created_at')

    my_auctions = Auction.objects.filter(
        product__seller=request.user
    ).order_by('-created_at')

    # -----------------------------------------------------
    # DASHBOARD CONTEXT
    # -----------------------------------------------------

    context = {
        'user': user,

        # Current mode
        'mode': mode,

        # Seller data
        'my_products_count': my_products.count(),
        'my_auctions_count': my_auctions.count(),
        'my_products': my_products,
        'my_auctions': my_auctions,
    }

    return render(
        request,
        'dashboard.html',
        context
    )
#=========================================================
# SWITCH MODE
#=========================================================
@login_required
def switch_mode(request, mode):
    """
    Switch the logged-in user's dashboard mode.

    Mode is stored in the session, not the database.
    """

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
        'You have been logged out.'
    )

    return redirect('login')


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

            # After saving profile, go back to Dashboard
            return redirect('dashboard')

    else:

        form = ProfileForm(instance=profile)

    return render(
        request,
        'edit_profile.html',
        {
            'form': form,
            'profile': profile,
        }
    )
@login_required
def add_product(request):
    # Only logged-in users can add products.
    # The seller will always be the currently logged-in user.
    if request.method == 'POST':
        form = ProductForm(request.POST)

        if form.is_valid():
            product = form.save(commit=False)
            product.seller = request.user
            product.save()

            messages.success(
                request,
                'Product added successfully!'
            )

            return redirect('create_auction', product_id=product.id)

    else:
        form = ProductForm()

    return render(
        request,
        'add_product.html',
        {'form': form}
    )
@login_required
def edit_product(request, product_id):

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
@login_required
def create_auction(request, product_id):
    product = Product.objects.get(
        id=product_id,
        seller=request.user
    )

    if request.method == 'POST':
        form = AuctionForm(request.POST)

        if form.is_valid():
            auction = form.save(commit=False)
            auction.product = product
            auction.starting_bid=product.starting_price
            auction.current_highest_bid=product.starting_price
            auction.status = 'SCHEDULED'
            auction.save()

            messages.success(
                request,
                'Auction created successfully!'
            )

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
@login_required
def seller_products(request):
    products = Product.objects.filter(
        seller=request.user
    ).order_by('-created_at')

    return render(
        request,
        'seller_products.html',
        {
            'products': products,
        }
    )
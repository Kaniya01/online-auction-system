from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from .forms import RegistrationForm,ProfileForm
from .models import Profile


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


# =========================================================
# DASHBOARD
# =========================================================

@login_required
def dashboard(request):

    """
    Main authenticated user dashboard.

    The dashboard will use the logged-in user's
    database information.

    No sample or hard-coded user data is created here.
    """

    user = request.user


    # -----------------------------------------------------
    # TEMPORARY BASIC CONTEXT
    # -----------------------------------------------------
    #
    # We are intentionally starting with only the user.
    #
    # Once we match the dashboard queries to the exact
    # fields in models.py, we will add:
    #
    # active_bids
    # won_auctions
    # my_products
    # my_auctions
    # ending_auctions
    # notifications
    #
    # This prevents us from guessing your model fields.
    # -----------------------------------------------------

    context = {

        'user': user,

    }


    return render(
        request,
        'dashboard.html',
        context
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

    return redirect('login')
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

            return redirect('profile')

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
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from .forms import RegistrationForm
from .models import Profile


def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            full_name = form.cleaned_data['full_name']
            phone_number = form.cleaned_data['phone_number']
            role = form.cleaned_data['role']

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            Profile.objects.create(
                user=user,
                full_name=full_name,
                phone_number=phone_number,
                role=role
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
        'auction/register.html',
        {'form': form}
    )


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

            try:
                role = user.profile.role
            except Profile.DoesNotExist:
                messages.error(request, 'User profile not found.')
                return redirect('login')

            # For now, send all authenticated users
            # to the existing dashboard preview.
            if role in ['BUYER', 'SELLER', 'ADMIN']:
                return redirect('dashboard_preview')

        messages.error(request, 'Invalid username or password.')

    return render(
        request,
        'auction/login.html'
    )


def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')
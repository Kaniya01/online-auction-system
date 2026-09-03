from django import forms
from django.contrib.auth.models import User
from .models import Profile

class RegistrationForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    password = forms.CharField(
        widget=forms.PasswordInput
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput
    )

    full_name = forms.CharField(max_length=150)
    phone_number = forms.CharField(max_length=15)

    def clean_username(self):
        username = self.cleaned_data['username']

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(
                'Username already exists.'
            )

        return username

    def clean_email(self):
        email = self.cleaned_data['email']

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                'Email already exists.'
            )

        return email

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                raise forms.ValidationError(
                    'Passwords do not match.'
                )

        return cleaned_data



class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'full_name',
            'phone_number',
            'profile_picture',
        ]

        widgets = {
            'full_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter your full name',
                }
            ),
            'phone_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter your phone number',
                }
            ),
            'profile_picture': forms.ClearableFileInput(
                attrs={
                    'class': 'form-control',
                }
            ),
        }
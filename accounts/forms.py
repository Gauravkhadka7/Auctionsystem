from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Profile, User


class RegisterForm(UserCreationForm):
    ROLE_CHOICES = (
        (User.Role.BIDDER, "Bidder — I want to bid on items"),
        (User.Role.SELLER, "Seller — I want to list items for auction"),
    )

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    mobile_number = forms.CharField(max_length=20, required=True)
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect, initial=User.Role.BIDDER)
    citizenship_number = forms.CharField(max_length=50, required=True)
    citizenship_document = forms.FileField(required=False)
    address = forms.CharField(max_length=255, required=True)
    profile_photo = forms.ImageField(required=False)
    agree_terms = forms.BooleanField(required=True, label="I agree to the Terms & Conditions")

    class Meta:
        model = User
        fields = [
            "first_name", "last_name", "username", "email", "mobile_number",
            "password1", "password2",
        ]

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.mobile_number = self.cleaned_data["mobile_number"]
        user.role = self.cleaned_data["role"]
        user.is_active = True
        if commit:
            user.save()
            Profile.objects.update_or_create(
                user=user,
                defaults={
                    "address": self.cleaned_data.get("address", ""),
                    "citizenship_number": self.cleaned_data.get("citizenship_number", ""),
                    "citizenship_document": self.cleaned_data.get("citizenship_document"),
                    "photo": self.cleaned_data.get("profile_photo"),
                },
            )
        return user


class ResendVerificationForm(forms.Form):
    """Email-based resend form.

    It never reveals whether the address belongs to a real account: the view
    shows the same confirmation regardless of the lookup result.
    """

    email = forms.EmailField(
        required=True,
        label="Email address",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autofocus": True}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    mobile_number = forms.CharField(max_length=20)

    class Meta:
        model = Profile
        fields = [
            "photo", "address", "bio",
            "bank_name", "bank_account_number", "bank_account_holder",
            "esewa_number", "khalti_number",
        ]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields["first_name"].initial = self.user.first_name
            self.fields["last_name"].initial = self.user.last_name
            self.fields["email"].initial = self.user.email
            self.fields["mobile_number"].initial = self.user.mobile_number

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.email = self.cleaned_data["email"]
            self.user.mobile_number = self.cleaned_data["mobile_number"]
            if commit:
                self.user.save()
        if commit:
            profile.save()
        return profile


class VerificationDocumentForm(forms.ModelForm):
    """Used by winners to submit KYC + payout info before payment is released."""

    class Meta:
        model = Profile
        fields = [
            "citizenship_number", "citizenship_document",
            "bank_name", "bank_account_number", "bank_account_holder",
            "esewa_number", "khalti_number",
        ]

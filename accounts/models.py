from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse


class User(AbstractUser):
    """
    Custom user model. `role` drives which portal/dashboard a user lands on.
    Sellers and Bidders share this model; role-specific extra data (payout
    details, verification docs) lives on Profile.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        SELLER = "SELLER", "Seller"
        BIDDER = "BIDDER", "Bidder"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BIDDER)
    mobile_number = models.CharField(max_length=20, blank=True)
    is_email_verified = models.BooleanField(default=False)
    is_kyc_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_seller(self):
        return self.role == self.Role.SELLER

    @property
    def is_bidder(self):
        return self.role == self.Role.BIDDER


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    photo = models.ImageField(upload_to="profile_photos/", blank=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    citizenship_number = models.CharField(max_length=50, blank=True)
    citizenship_document = models.FileField(
        upload_to="verification_docs/citizenship/", blank=True, null=True
    )
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=50, blank=True)
    bank_account_holder = models.CharField(max_length=100, blank=True)
    esewa_number = models.CharField(max_length=20, blank=True)
    khalti_number = models.CharField(max_length=20, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"Profile of {self.user}"

    def get_absolute_url(self):
        return reverse("accounts:profile")


class EmailOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    code = models.CharField(max_length=6)
    purpose = models.CharField(
        max_length=20,
        choices=[("VERIFY", "Email Verification"), ("RESET", "Password Reset")],
        default="VERIFY",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"OTP({self.purpose}) for {self.user}"

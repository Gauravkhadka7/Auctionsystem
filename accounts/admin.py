from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import EmailOTP, Profile, User


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "email", "role", "is_email_verified", "is_kyc_verified", "is_active")
    list_filter = ("role", "is_email_verified", "is_kyc_verified", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Auction System", {"fields": ("role", "mobile_number", "is_email_verified", "is_kyc_verified")}),
    )


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "code", "is_used", "created_at")
    list_filter = ("purpose", "is_used")

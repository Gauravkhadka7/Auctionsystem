from django.contrib import admin
from django.utils import timezone

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("winner", "payer", "method", "amount", "status", "created_at")
    list_filter = ("method", "status")
    actions = ["mark_verified", "mark_rejected"]

    @admin.action(description="Mark selected payments as verified")
    def mark_verified(self, request, queryset):
        updated = queryset.update(status=Payment.Status.VERIFIED, verified_at=timezone.now())
        for payment in queryset:
            payment.winner.is_payment_verified = True
            payment.winner.save(update_fields=["is_payment_verified"])
        self.message_user(request, f"{updated} payment(s) verified.")

    @admin.action(description="Mark selected payments as rejected")
    def mark_rejected(self, request, queryset):
        queryset.update(status=Payment.Status.REJECTED)

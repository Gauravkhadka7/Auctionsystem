from django.conf import settings
from django.db import models


class Payment(models.Model):
    class Method(models.TextChoices):
        ESEWA = "ESEWA", "eSewa"
        KHALTI = "KHALTI", "Khalti"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        CASH = "CASH", "Cash"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"

    winner = models.ForeignKey("winners.Winner", on_delete=models.CASCADE, related_name="payments")
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=20, choices=Method.choices)
    transaction_id = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt = models.FileField(upload_to="payment_receipts/", blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.amount} for {self.winner} ({self.status})"

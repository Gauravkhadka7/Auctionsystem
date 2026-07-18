from django.conf import settings
from django.db import models


class Winner(models.Model):
    product = models.OneToOneField("products.Product", on_delete=models.CASCADE, related_name="winner")
    bidder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wins")
    winning_price = models.DecimalField(max_digits=12, decimal_places=2)

    is_verification_submitted = models.BooleanField(default=False)
    is_payment_verified = models.BooleanField(default=False)
    is_delivered = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.bidder} won {self.product} for {self.winning_price}"

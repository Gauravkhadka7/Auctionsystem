from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Bid(models.Model):
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bids")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-amount", "created_at"]
        indexes = [models.Index(fields=["product", "-amount"])]

    def __str__(self):
        return f"{self.bidder} bid {self.amount} on {self.product}"

    def clean(self):
        product = self.product
        if self.amount is None or not self.amount.is_finite() or self.amount <= 0:
            raise ValidationError("Enter a valid positive bid amount.")
        if product.status != product.Status.LIVE:
            raise ValidationError("Bidding is only allowed on live auctions.")
        if timezone.now() >= product.auction_end:
            raise ValidationError("This auction has ended.")
        if self.bidder_id == product.seller_id:
            raise ValidationError("Sellers can't bid on their own product.")
        if self.amount < product.minimum_next_bid:
            raise ValidationError(f"Bid must be at least {product.minimum_next_bid}.")

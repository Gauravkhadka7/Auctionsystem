from django.conf import settings
from django.db import models


class WatchlistItem(models.Model):
    """A bidder's saved product. One row per (user, product) pair."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watchlist_items"
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="watchlisted_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "product")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} watching {self.product}"

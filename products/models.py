from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Product(models.Model):
    """
    A Product IS the auction listing: it carries both the item details and
    the auction schedule/pricing. `status` is the single source of truth for
    lifecycle state and is transitioned by auctions.services.sync_auction_states().
    """

    class Condition(models.TextChoices):
        NEW = "NEW", "New"
        LIKE_NEW = "LIKE_NEW", "Like New"
        USED = "USED", "Used"
        REFURBISHED = "REFURBISHED", "Refurbished"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Approval"
        UPCOMING = "UPCOMING", "Upcoming"
        LIVE = "LIVE", "Live"
        CLOSED = "CLOSED", "Closed"
        REJECTED = "REJECTED", "Rejected"
        SUSPENDED = "SUSPENDED", "Suspended"
        CANCELLED = "CANCELLED", "Cancelled"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="products"
    )
    category = models.ForeignKey(
        "categories.Category", on_delete=models.PROTECT, related_name="products"
    )
    subcategory = models.ForeignKey(
        "categories.SubCategory", on_delete=models.PROTECT, related_name="products",
        null=True, blank=True,
    )

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.USED)
    description = models.TextField()
    main_image = models.ImageField(upload_to="products/main/")

    starting_price = models.DecimalField(max_digits=12, decimal_places=2)
    reserve_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    bid_increment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("10.00"))
    current_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    auction_start = models.DateTimeField()
    auction_end = models.DateTimeField()

    delivery_info = models.TextField(blank=True, help_text="Shipping / pickup details for the winner")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    is_featured = models.BooleanField(default=False)
    admin_remarks = models.TextField(blank=True)

    view_count = models.PositiveIntegerField(default=0)
    extension_count = models.PositiveIntegerField(
        default=0,
        help_text="Times auction_end was pushed back by a last-second bid.",
    )
    ending_soon_notified = models.BooleanField(
        default=False,
        help_text="Internal flag: the 'ending soon' reminder already fired for this auction window.",
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable location, e.g. 'Kathmandu, Nepal'",
    )
    pickup_available = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["auction_start"]),
            models.Index(fields=["auction_end"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:200]
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        if self.current_price is None:
            self.current_price = self.starting_price
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("products:detail", args=[self.slug])

    @property
    def is_live(self):
        return self.status == self.Status.LIVE

    @property
    def minimum_next_bid(self):
        return (self.current_price or self.starting_price) + self.bid_increment

    @property
    def total_bids(self):
        return self.bids.count()

    @property
    def total_bidders(self):
        return self.bids.values("bidder_id").distinct().count()

    @property
    def time_remaining_seconds(self):
        now = timezone.now()
        target = self.auction_end if self.status == self.Status.LIVE else self.auction_start
        delta = (target - now).total_seconds()
        return max(0, int(delta))

    @property
    def reserve_met(self):
        if not self.reserve_price:
            return True
        return (self.current_price or 0) >= self.reserve_price


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/gallery/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.title}"


class ProductSpecification(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="specifications")
    name = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name}: {self.value}"


class Comment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Comment by {self.user} on {self.product}"

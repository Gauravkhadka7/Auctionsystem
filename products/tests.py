import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from categories.models import Category

from .forms import validate_image_upload
from .models import Product

User = get_user_model()


def make_image(name="item.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class StartSellingTestCase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Art")
        self.url = reverse("products:product_create")
        self.seller = User.objects.create_user(
            "seller", password="pw12345!", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            "bidder", password="pw12345!", role=User.Role.BIDDER
        )

    # -- access control -----------------------------------------------------
    def test_seller_can_access_selling_page(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "products/product_form.html")

    def test_bidder_is_redirected_away(self):
        self.client.force_login(self.bidder)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard_redirect"))

    def test_anonymous_is_redirected_to_login_with_next(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))
        self.assertIn("next=", response.url)

    # -- submission payload -------------------------------------------------
    def _payload(self):
        now = timezone.now()
        payload = {
            "title": "Antique Vase",
            "category": self.category.pk,
            "subcategory": "",
            "brand": "Unknown",
            "condition": Product.Condition.USED,
            "description": "A lovely vase.",
            "starting_price": "100.00",
            "reserve_price": "150.00",
            "bid_increment": "10.00",
            "auction_start": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "auction_end": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "delivery_info": "Pickup in Kathmandu.",
            "main_image": make_image("main.png"),
            "images-TOTAL_FORMS": "1",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "1000",
            "images-0-image": make_image("gallery.png"),
            "specifications-TOTAL_FORMS": "1",
            "specifications-INITIAL_FORMS": "0",
            "specifications-MIN_NUM_FORMS": "0",
            "specifications-MAX_NUM_FORMS": "1000",
            "specifications-0-name": "Material",
            "specifications-0-value": "Ceramic",
        }
        return payload

    # -- valid save ---------------------------------------------------------
    def test_valid_submission_creates_pending_product_for_seller(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url, self._payload())
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("products:my_products"))

        product = Product.objects.get()
        self.assertEqual(product.seller, self.seller)
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.current_price, Decimal("100.00"))
        self.assertEqual(product.view_count, 0)
        self.assertEqual(product.images.count(), 1)
        self.assertEqual(product.specifications.count(), 1)

    def test_new_product_defaults_view_count_to_zero(self):
        now = timezone.now()
        product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="No Views Yet",
            description="Created without supplying view_count.",
            main_image="products/main/test.png",
            starting_price="10.00",
            auction_start=now + timedelta(days=1),
            auction_end=now + timedelta(days=2),
        )
        self.assertEqual(product.view_count, 0)

    # -- invalid submissions ------------------------------------------------
    def _assert_rejected(self, **overrides):
        self.client.force_login(self.seller)
        payload = self._payload()
        payload.update(overrides)
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.exists())

    def test_end_before_start_is_rejected(self):
        now = timezone.now()
        self._assert_rejected(
            auction_start=(now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            auction_end=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        )

    def test_start_in_the_past_is_rejected(self):
        now = timezone.now()
        self._assert_rejected(
            auction_start=(now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            auction_end=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        )

    def test_reserve_below_starting_price_is_rejected(self):
        self._assert_rejected(starting_price="200.00", reserve_price="150.00")

    def test_non_positive_bid_increment_is_rejected(self):
        self._assert_rejected(bid_increment="0.00")

    def test_listing_without_images_is_rejected(self):
        self._assert_rejected(
            **{
                "images-TOTAL_FORMS": "0",
                "images-0-image": "",
            }
        )

    def test_non_image_upload_is_rejected(self):
        bad_file = SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")
        self._assert_rejected(**{"images-0-image": bad_file})

    # -- standalone image validation ---------------------------------------
    def test_oversized_image_is_rejected(self):
        with patch("products.forms.MAX_IMAGE_SIZE_MB", 0):
            with self.assertRaises(ValidationError):
                validate_image_upload(make_image())


class ViewCounterTestCase(TestCase):
    """Public listing views are counted atomically; the seller's own visits
    are not."""

    def setUp(self):
        self.seller = User.objects.create_user(
            "vc_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.visitor = User.objects.create_user(
            "vc_visitor", password="pw12345!", role=User.Role.BIDDER
        )
        self.category = Category.objects.create(name="Views")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Viewed Lot",
            description="d",
            main_image="products/main/vc.png",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )
        self.url = reverse("products:detail", args=[self.product.slug])

    def test_anonymous_visit_increments_counter(self):
        self.client.get(self.url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 1)

    def test_each_visit_counts_repeatedly(self):
        self.client.get(self.url)
        self.client.get(self.url)
        self.client.get(self.url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 3)

    def test_seller_viewing_own_lot_does_not_count(self):
        self.client.force_login(self.seller)
        self.client.get(self.url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 0)

    def test_other_authenticated_visitor_counts(self):
        self.client.force_login(self.visitor)
        self.client.get(self.url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 1)

    def test_detail_page_renders_current_view_count(self):
        Product.objects.filter(pk=self.product.pk).update(view_count=6)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # 6 before this visit + 1 for this visit, rendered back to the client.
        self.assertContains(response, "7 views")

    def test_list_page_renders_view_count_without_incrementing(self):
        Product.objects.filter(pk=self.product.pk).update(view_count=5)
        response = self.client.get(reverse("products:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5 views")
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 5, "listing pages never count views")

    def test_my_products_table_shows_views_column(self):
        Product.objects.filter(pk=self.product.pk).update(view_count=9)
        self.client.force_login(self.seller)
        response = self.client.get(reverse("products:my_products"))
        self.assertContains(response, "<th>Views</th>", html=False)
        self.assertContains(response, '<i class="bi bi-eye"></i> 9</td>', html=False)

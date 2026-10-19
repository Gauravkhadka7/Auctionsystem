from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from categories.models import Category
from products.models import Product

from .models import WatchlistItem

User = get_user_model()


class WatchlistTestCase(TestCase):
    def setUp(self):
        self.bidder = User.objects.create_user("wl_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.other_bidder = User.objects.create_user("wl_bidder2", password="pw12345!", role=User.Role.BIDDER)
        self.seller = User.objects.create_user("wl_seller", password="pw12345!", role=User.Role.SELLER)
        self.category = Category.objects.create(name="Watchlist Cat")

    def make_product(self, status=Product.Status.LIVE, title="Item", start_minutes=-60, end_minutes=60):
        now = timezone.now()
        return Product.objects.create(
            seller=self.seller,
            category=self.category,
            title=title,
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now + timedelta(minutes=start_minutes),
            auction_end=now + timedelta(minutes=end_minutes),
            status=status,
        )


class WatchlistModelTests(WatchlistTestCase):
    def test_unique_user_product_constraint(self):
        product = self.make_product()
        WatchlistItem.objects.create(user=self.bidder, product=product)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WatchlistItem.objects.create(user=self.bidder, product=product)

    def test_registered_in_admin(self):
        self.assertIn(WatchlistItem, admin.site._registry)


class ToggleWatchlistTests(WatchlistTestCase):
    def setUp(self):
        super().setUp()
        self.product = self.make_product()
        self.url = reverse("watchlist:toggle", args=[self.product.slug])

    def post_ajax(self):
        return self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_bidder_adds_via_ajax(self):
        self.client.force_login(self.bidder)
        response = self.post_ajax()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["watching"])
        self.assertEqual(data["watchers_count"], 1)
        self.assertTrue(
            WatchlistItem.objects.filter(user=self.bidder, product=self.product).exists()
        )

    def test_bidder_removes_via_ajax(self):
        WatchlistItem.objects.create(user=self.bidder, product=self.product)
        self.client.force_login(self.bidder)
        response = self.post_ajax()
        data = response.json()
        self.assertFalse(data["watching"])
        self.assertEqual(data["watchers_count"], 0)
        self.assertFalse(
            WatchlistItem.objects.filter(user=self.bidder, product=self.product).exists()
        )

    def test_toggle_requires_post(self):
        self.client.force_login(self.bidder)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_seller_cannot_watch(self):
        self.client.force_login(self.seller)
        response = self.post_ajax()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_cannot_add_closed_auction_ajax(self):
        closed = self.make_product(status=Product.Status.CLOSED, end_minutes=-5)
        self.client.force_login(self.bidder)
        response = self.client.post(
            reverse("watchlist:toggle", args=[closed.slug]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_cannot_add_closed_auction_without_js(self):
        closed = self.make_product(status=Product.Status.CLOSED, end_minutes=-5)
        self.client.force_login(self.bidder)
        response = self.client.post(reverse("watchlist:toggle", args=[closed.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_can_remove_closed_auction(self):
        closed = self.make_product(status=Product.Status.CLOSED, end_minutes=-5)
        WatchlistItem.objects.create(user=self.bidder, product=closed)
        self.client.force_login(self.bidder)
        response = self.client.post(
            reverse("watchlist:toggle", args=[closed.slug]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["watching"])
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_cannot_add_upcoming_after_other_user(self):
        # Sanity: counts are per product, not global toggles.
        upcoming = self.make_product(status=Product.Status.UPCOMING, start_minutes=30, end_minutes=90)
        self.client.force_login(self.bidder)
        self.client.post(
            reverse("watchlist:toggle", args=[upcoming.slug]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.client.force_login(self.other_bidder)
        response = self.client.post(
            reverse("watchlist:toggle", args=[upcoming.slug]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.json()["watchers_count"], 2)

    def test_non_ajax_toggle_redirects_and_creates(self):
        self.client.force_login(self.bidder)
        response = self.client.post(self.url, {"next": self.product.get_absolute_url()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.product.get_absolute_url())
        self.assertTrue(
            WatchlistItem.objects.filter(user=self.bidder, product=self.product).exists()
        )

    def test_unsafe_next_is_ignored(self):
        self.client.force_login(self.bidder)
        response = self.client.post(self.url, {"next": "https://evil.example.com/"})
        self.assertEqual(response.url, self.product.get_absolute_url())


class MyWatchlistViewTests(WatchlistTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("watchlist:my_watchlist")
        self.live = self.make_product(title="Live One")
        self.upcoming = self.make_product(
            status=Product.Status.UPCOMING, title="Upcoming One", start_minutes=30, end_minutes=90
        )

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_seller_is_denied(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_lists_only_current_users_items(self):
        WatchlistItem.objects.create(user=self.bidder, product=self.live)
        WatchlistItem.objects.create(user=self.other_bidder, product=self.upcoming)
        self.client.force_login(self.bidder)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        items = list(response.context["watchlist_items"])
        self.assertEqual([i.product for i in items], [self.live])

    def test_status_filter(self):
        WatchlistItem.objects.create(user=self.bidder, product=self.live)
        WatchlistItem.objects.create(user=self.bidder, product=self.upcoming)
        self.client.force_login(self.bidder)

        response = self.client.get(self.url, {"status": "UPCOMING"})
        items = list(response.context["watchlist_items"])
        self.assertEqual([i.product for i in items], [self.upcoming])

        response = self.client.get(self.url, {"status": "LIVE"})
        items = list(response.context["watchlist_items"])
        self.assertEqual([i.product for i in items], [self.live])

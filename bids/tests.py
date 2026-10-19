from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from categories.models import Category
from notifications.models import Notification
from products.models import Product

from .models import Bid
from .services import BidError, place_bid

User = get_user_model()


class BidTestCase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("bidder", password="pw12345!", role=User.Role.BIDDER)
        self.rival = User.objects.create_user("rival", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Watches")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Vintage Watch",
            description="A watch",
            main_image="products/main/watch.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )

    def test_valid_bid_updates_price_and_minimum(self):
        bid = place_bid(self.product, self.bidder, Decimal("110.00"))
        self.product.refresh_from_db()
        self.assertEqual(bid.amount, Decimal("110.00"))
        self.assertEqual(self.product.current_price, Decimal("110.00"))
        self.assertEqual(self.product.minimum_next_bid, Decimal("120.00"))

    def test_bid_below_minimum_rejected(self):
        with self.assertRaises(BidError):
            place_bid(self.product, self.bidder, Decimal("105.00"))

    def test_seller_cannot_bid(self):
        with self.assertRaises(BidError):
            place_bid(self.product, self.seller, Decimal("110.00"))

    def test_cannot_bid_on_non_live_auction(self):
        self.product.status = Product.Status.CLOSED
        self.product.save(update_fields=["status"])
        with self.assertRaises(BidError):
            place_bid(self.product, self.bidder, Decimal("110.00"))

    def test_cannot_bid_after_auction_end(self):
        self.product.auction_end = timezone.now() - timedelta(minutes=1)
        self.product.save(update_fields=["auction_end"])
        with self.assertRaises(BidError):
            place_bid(self.product, self.bidder, Decimal("110.00"))

    def test_nan_amount_is_rejected_not_crash(self):
        # Regression: Decimal("NaN") comparisons raise InvalidOperation,
        # which previously escaped as a 500 error.
        with self.assertRaises(BidError):
            place_bid(self.product, self.bidder, Decimal("NaN"))

    def test_infinite_and_negative_amounts_rejected(self):
        for bad in (Decimal("Infinity"), Decimal("-Infinity"), Decimal("-5.00"), Decimal("0")):
            with self.assertRaises(BidError):
                place_bid(self.product, self.bidder, bad)

    def test_leader_is_notified_when_outbid(self):
        place_bid(self.product, self.bidder, Decimal("110.00"))
        place_bid(self.product, self.rival, Decimal("120.00"))
        self.assertTrue(
            Notification.objects.filter(user=self.bidder, message__icontains="outbid").exists()
        )

    def test_place_bid_publishes_update_to_auction_group(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        calls = []

        async def fake_group_send(group, message):
            calls.append((group, message))

        layer = SimpleNamespace(group_send=fake_group_send)
        with patch("channels.layers.get_channel_layer", return_value=layer):
            place_bid(self.product, self.bidder, Decimal("110.00"))

        self.assertEqual(len(calls), 1)
        group, message = calls[0]
        self.assertEqual(group, f"auction_{self.product.slug}")
        self.assertEqual(message["type"], "auction.update")
        self.assertEqual(message["payload"]["current_price"], "110.00")
        self.assertEqual(message["payload"]["leader"], "bidder")


class BidAjaxViewTestCase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("ajax_seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("ajax_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Coin")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Gold Coin",
            description="A coin",
            main_image="products/main/coin.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )
        self.url = reverse("bids:place_ajax", args=[self.product.slug])

    def test_ajax_bid_success(self):
        self.client.force_login(self.bidder)
        response = self.client.post(self.url, {"amount": "110.00"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["current_price"], "110.00")
        self.assertEqual(data["leader"], "ajax_bidder")

    def test_ajax_nan_amount_returns_400_not_500(self):
        self.client.force_login(self.bidder)
        response = self.client.post(self.url, {"amount": "NaN"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_ajax_requires_login(self):
        response = self.client.post(self.url, {"amount": "110.00"})
        self.assertEqual(response.status_code, 302)

    def test_status_endpoint_reports_time_remaining(self):
        response = self.client.get(reverse("bids:status_ajax", args=[self.product.slug]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "LIVE")
        self.assertGreater(data["time_remaining_seconds"], 0)
        self.assertEqual(Bid.objects.count(), 0)

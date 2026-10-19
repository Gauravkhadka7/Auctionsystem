from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from bids.services import place_bid
from categories.models import Category
from notifications.models import Notification
from products.models import Product
from winners.models import Winner

from .services import sync_auction_states

User = get_user_model()


class AuctionLifecycleTestCase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("lc_seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("lc_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Art")

    def make_product(self, status, start_delta, end_delta, **kwargs):
        now = timezone.now()
        return Product.objects.create(
            seller=self.seller,
            category=self.category,
            title=kwargs.pop("title", "Auction Item"),
            description="d",
            main_image="products/main/x.jpg",
            starting_price=kwargs.pop("starting_price", Decimal("100.00")),
            bid_increment=Decimal("10.00"),
            reserve_price=kwargs.pop("reserve_price", None),
            auction_start=now + start_delta,
            auction_end=now + end_delta,
            status=status,
            **kwargs,
        )

    def test_upcoming_auction_goes_live(self):
        product = self.make_product(
            Product.Status.UPCOMING, timedelta(minutes=-5), timedelta(hours=1)
        )
        result = sync_auction_states()
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.LIVE)
        self.assertEqual(result["started"], 1)
        self.assertTrue(
            Notification.objects.filter(user=self.seller, message__icontains="gone live").exists()
        )

    def test_expired_auction_closes_and_creates_winner(self):
        product = self.make_product(
            Product.Status.LIVE, timedelta(hours=-2), timedelta(minutes=-5)
        )
        # Place bid while still live, then let it expire.
        product.auction_end = timezone.now() + timedelta(minutes=5)
        product.save(update_fields=["auction_end"])
        place_bid(product, self.bidder, Decimal("110.00"))
        product.auction_end = timezone.now() - timedelta(minutes=1)
        product.save(update_fields=["auction_end"])

        result = sync_auction_states()
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.CLOSED)
        self.assertEqual(result["closed"], 1)
        winner = Winner.objects.get(product=product)
        self.assertEqual(winner.bidder, self.bidder)
        self.assertEqual(winner.winning_price, Decimal("110.00"))
        self.assertTrue(
            Notification.objects.filter(user=self.bidder, message__icontains="won").exists()
        )
        self.assertTrue(
            Notification.objects.filter(user=self.seller, message__icontains="Winner").exists()
        )

    def test_expired_auction_reserve_not_met_has_no_winner(self):
        product = self.make_product(
            Product.Status.LIVE,
            timedelta(hours=-2),
            timedelta(minutes=5),
            reserve_price=Decimal("500.00"),
        )
        place_bid(product, self.bidder, Decimal("110.00"))
        product.auction_end = timezone.now() - timedelta(minutes=1)
        product.save(update_fields=["auction_end"])

        sync_auction_states()
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.CLOSED)
        self.assertFalse(Winner.objects.filter(product=product).exists())
        self.assertTrue(
            Notification.objects.filter(
                user=self.seller, message__icontains="no winner"
            ).exists()
        )

    def test_time_remaining_counts_down_to_end_when_live(self):
        product = self.make_product(
            Product.Status.LIVE, timedelta(minutes=-1), timedelta(minutes=5)
        )
        self.assertAlmostEqual(product.time_remaining_seconds, 300, delta=5)

    def test_time_remaining_zero_when_ended(self):
        product = self.make_product(
            Product.Status.LIVE, timedelta(hours=-2), timedelta(minutes=-1)
        )
        # Status hasn't been synced yet but the clock has passed.
        self.assertEqual(product.time_remaining_seconds, 0)


class AuctionWebSocketTestCase(TransactionTestCase):
    def setUp(self):
        self.seller = User.objects.create_user("ws_seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("ws_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Toys")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Robot",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )
        self.group = f"auction_{self.product.slug}"

    async def test_connect_sends_current_snapshot(self):
        from channels.testing import WebsocketCommunicator

        from auction_system.asgi import application

        communicator = WebsocketCommunicator(
            application, f"/ws/auction/{self.product.slug}/"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        snapshot = await communicator.receive_json_from()
        self.assertEqual(snapshot["type"], "auction.update")
        self.assertEqual(snapshot["status"], "LIVE")
        self.assertEqual(snapshot["current_price"], "100.00")
        self.assertEqual(snapshot["total_bids"], 0)

        await communicator.disconnect()

    async def test_group_broadcast_is_pushed_to_client(self):
        from channels.layers import get_channel_layer
        from channels.testing import WebsocketCommunicator

        from auction_system.asgi import application

        communicator = WebsocketCommunicator(
            application, f"/ws/auction/{self.product.slug}/"
        )
        await communicator.connect()
        await communicator.receive_json_from()  # snapshot

        payload = {
            "type": "auction.update",
            "event": "bid",
            "slug": self.product.slug,
            "status": "LIVE",
            "current_price": "110.00",
            "minimum_next_bid": "120.00",
            "total_bids": 1,
            "total_bidders": 1,
            "time_remaining_seconds": 100,
            "leader": "ws_bidder",
        }
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            self.group, {"type": "auction.update", "payload": payload}
        )

        update = await communicator.receive_json_from(timeout=2)
        self.assertEqual(update["current_price"], "110.00")
        self.assertEqual(update["total_bids"], 1)
        self.assertEqual(update["leader"], "ws_bidder")

        await communicator.disconnect()

    async def test_unknown_slug_is_rejected(self):
        from channels.testing import WebsocketCommunicator

        from auction_system.asgi import application

        communicator = WebsocketCommunicator(application, "/ws/auction/does-not-exist/")
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

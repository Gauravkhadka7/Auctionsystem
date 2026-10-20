from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from bids.services import place_bid
from categories.models import Category
from notifications.models import Notification
from products.models import Product
from watchlist.models import WatchlistItem
from winners.models import Winner

from .broadcast import broadcast_auction
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


@override_settings(
    SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3
)
class AntiSnipingClosingTests(TestCase):
    """An extended deadline must survive the closing job."""

    def setUp(self):
        self.seller = User.objects.create_user("close_seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("close_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Closing")

    def make_live(self, end_in):
        now = timezone.now()
        return Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Cutting It Close",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + end_in,
            status=Product.Status.LIVE,
        )

    def test_extended_auction_is_not_closed_early(self):
        product = self.make_live(timedelta(seconds=30))
        place_bid(product, self.bidder, Decimal("110.00"))
        product.refresh_from_db()
        self.assertEqual(product.extension_count, 1)

        result = sync_auction_states()
        product.refresh_from_db()

        self.assertEqual(result["closed"], 0, "the extended deadline hasn't passed")
        self.assertEqual(product.status, Product.Status.LIVE)
        self.assertFalse(Winner.objects.filter(product=product).exists())

    def test_auction_closes_after_extended_deadline_passes(self):
        product = self.make_live(timedelta(seconds=30))
        place_bid(product, self.bidder, Decimal("110.00"))

        # Simulate the clock finally running past the *extended* deadline.
        Product.objects.filter(pk=product.pk).update(
            auction_end=timezone.now() - timedelta(seconds=1)
        )
        result = sync_auction_states()
        product.refresh_from_db()

        self.assertEqual(result["closed"], 1)
        self.assertEqual(product.status, Product.Status.CLOSED)
        winner = Winner.objects.get(product=product)
        self.assertEqual(winner.winning_price, Decimal("110.00"))

    def test_extended_deadline_is_what_gets_broadcast_on_close(self):
        product = self.make_live(timedelta(seconds=30))
        place_bid(product, self.bidder, Decimal("110.00"))
        product.refresh_from_db()
        extended_end = product.auction_end

        # Move the clock past the extended deadline instead of rewriting the
        # row, so the broadcast still carries the stored (extended) deadline.
        future_now = timezone.now() + timedelta(minutes=10)
        with patch("auctions.services.timezone.now", return_value=future_now):
            with patch("auctions.services.broadcast_auction") as mock_broadcast:
                sync_auction_states()

        mock_broadcast.assert_called_once()
        broadcasted_product = mock_broadcast.call_args.args[0]
        self.assertEqual(mock_broadcast.call_args.kwargs["event"], "closed")
        self.assertEqual(
            broadcasted_product.auction_end,
            extended_end,
            "the broadcaster must carry the extended deadline, not a pre-extension one",
        )


@override_settings(AUCTION_ENDING_SOON_MINUTES=5, SNIP_WINDOW_SECONDS=60)
class EndingSoonNotificationTests(TestCase):
    """One-shot 'ending soon' reminder when a live lot enters the final window."""

    def setUp(self):
        self.seller = User.objects.create_user("soon_seller", password="pw12345!", role=User.Role.SELLER)
        self.leader = User.objects.create_user("soon_leader", password="pw12345!", role=User.Role.BIDDER)
        self.watcher = User.objects.create_user("soon_watcher", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Timers")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Ending Soonest",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(minutes=2),
            status=Product.Status.LIVE,
        )
        WatchlistItem.objects.create(user=self.watcher, product=self.product)

    def count_messages(self, user):
        return Notification.objects.filter(
            user=user, message__icontains="ending within"
        ).count()

    def test_in_window_auction_notifies_seller_leader_and_watcher_once(self):
        place_bid(self.product, self.leader, Decimal("110.00"))

        result = sync_auction_states()
        self.assertEqual(result["ending_soon"], 1)

        for user in (self.seller, self.leader, self.watcher):
            self.assertEqual(self.count_messages(user), 1)

        self.product.refresh_from_db()
        self.assertTrue(self.product.ending_soon_notified)

        # A later sync must not repeat the reminder.
        result = sync_auction_states()
        self.assertEqual(result["ending_soon"], 0)
        for user in (self.seller, self.leader, self.watcher):
            self.assertEqual(self.count_messages(user), 1)

    def test_auction_outside_window_is_not_notified(self):
        Product.objects.filter(pk=self.product.pk).update(
            auction_end=timezone.now() + timedelta(hours=1)
        )
        result = sync_auction_states()
        self.assertEqual(result["ending_soon"], 0)
        for user in (self.seller, self.leader, self.watcher):
            self.assertEqual(self.count_messages(user), 0)

    def test_ending_soon_broadcasts_event_and_stops(self):
        with patch("auctions.services.broadcast_auction") as mock_broadcast:
            sync_auction_states()
            self.assertEqual(mock_broadcast.call_count, 1)
            self.assertEqual(mock_broadcast.call_args.kwargs["event"], "ending_soon")
            self.assertEqual(
                mock_broadcast.call_args.args[0].pk, self.product.pk
            )

            sync_auction_states()
            self.assertEqual(mock_broadcast.call_count, 1, "one-shot reminder")

    def test_ending_soon_notified_even_without_bids_or_watchers(self):
        WatchlistItem.objects.filter(product=self.product).delete()
        result = sync_auction_states()
        self.assertEqual(result["ending_soon"], 1)
        self.assertEqual(self.count_messages(self.seller), 1)
        self.assertEqual(self.count_messages(self.leader), 0)

    def test_activation_resets_stale_flag_for_new_window(self):
        # A product that comes up for sale again with a leftover flag must get
        # a fresh reminder for its current window.
        Product.objects.filter(pk=self.product.pk).update(
            status=Product.Status.UPCOMING,
            ending_soon_notified=True,
            auction_start=timezone.now() - timedelta(minutes=5),
            auction_end=timezone.now() + timedelta(hours=1),
        )
        result = sync_auction_states()
        self.assertEqual(result["started"], 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.LIVE)
        self.assertFalse(self.product.ending_soon_notified)


class BroadcastPayloadTests(TestCase):
    """Every WS frame carries the fields clients need to re-derive state."""

    def setUp(self):
        self.seller = User.objects.create_user("payload_seller", password="pw12345!", role=User.Role.SELLER)
        self.category = Category.objects.create(name="Payloads")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Payload Lot",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(minutes=30),
            status=Product.Status.LIVE,
            extension_count=2,
        )

    def test_payload_contains_deadline_and_extension_count(self):
        from types import SimpleNamespace

        calls = []

        async def fake_group_send(group, message):
            calls.append((group, message))

        with patch(
            "channels.layers.get_channel_layer",
            return_value=SimpleNamespace(group_send=fake_group_send),
        ):
            broadcast_auction(self.product, event="extended")

        self.assertEqual(len(calls), 1)
        group, message = calls[0]
        self.assertEqual(group, f"auction_{self.product.slug}")
        payload = message["payload"]
        self.assertEqual(message["type"], "auction.update")
        self.assertEqual(payload["event"], "extended")
        self.assertEqual(payload["auction_end"], self.product.auction_end.isoformat())
        self.assertEqual(payload["extension_count"], 2)
        self.assertEqual(payload["status"], "LIVE")
        self.assertIn("time_remaining_seconds", payload)

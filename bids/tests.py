import threading
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from categories.models import Category
from notifications.models import Notification
from products.models import Product
from watchlist.models import WatchlistItem

from .models import Bid
from .services import BidError, place_bid, sniping_extension_for

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

class AntiSnipingTests(TestCase):
    """Anti-sniping: late bids push the deadline back, never forward."""

    def setUp(self):
        self.seller = User.objects.create_user("snip_seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("snip_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.watcher = User.objects.create_user("snip_watcher", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Sneakers")
        self.product = self._product(end_in=timedelta(seconds=30))
        WatchlistItem.objects.create(user=self.watcher, product=self.product)

    def _product(self, **kwargs):
        now = timezone.now()
        status = kwargs.pop("status", Product.Status.LIVE)
        end_in = kwargs.pop("end_in", timedelta(hours=1))
        return Product.objects.create(
            seller=self.seller,
            category=self.category,
            title=kwargs.pop("title", "Rare Kicks"),
            description="d",
            main_image="products/main/x.jpg",
            starting_price=kwargs.pop("starting_price", Decimal("100.00")),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + end_in,
            status=status,
            **kwargs,
        )

    # -- pure rule ----------------------------------------------------------
    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_helper_returns_extension_inside_window(self):
        product = self._product(end_in=timedelta(seconds=30))
        before = timezone.now()
        new_end = sniping_extension_for(product)
        self.assertIsNotNone(new_end)
        self.assertGreater(new_end, product.auction_end)
        # The new deadline is "now + extension", measured within 10s of the call.
        self.assertAlmostEqual(
            (new_end - before).total_seconds(), 120, delta=10
        )

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_helper_returns_none_outside_window(self):
        product = self._product(end_in=timedelta(minutes=10))
        self.assertIsNone(sniping_extension_for(product))

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_helper_returns_none_when_extension_cap_reached(self):
        product = self._product(end_in=timedelta(seconds=30))
        Product.objects.filter(pk=product.pk).update(extension_count=3)
        product.refresh_from_db()
        self.assertIsNone(sniping_extension_for(product))

    @override_settings(SNIP_WINDOW_SECONDS=600, AUCTION_EXTENSION_MINUTES=1, AUCTION_MAX_EXTENSIONS=3)
    def test_helper_never_moves_deadline_earlier(self):
        # Inside the window, but "now + 1 min" is still before the existing
        # deadline (5 min out): the helper must decline rather than shorten.
        product = self._product(end_in=timedelta(minutes=5))
        self.assertIsNone(sniping_extension_for(product))

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_helper_returns_none_for_expired_or_non_live(self):
        expired = self._product(title="Expired", end_in=timedelta(seconds=-10))
        self.assertIsNone(sniping_extension_for(expired))
        upcoming = self._product(title="Upcoming", end_in=timedelta(seconds=30), status=Product.Status.UPCOMING)
        self.assertIsNone(sniping_extension_for(upcoming))

    # -- end-to-end through place_bid --------------------------------------
    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_bid_inside_window_extends_and_persists(self):
        before = timezone.now()
        place_bid(self.product, self.bidder, Decimal("110.00"))
        self.product.refresh_from_db()
        self.assertGreater(self.product.auction_end, before + timedelta(minutes=1))
        self.assertAlmostEqual(
            (self.product.auction_end - before).total_seconds(), 120, delta=15
        )
        self.assertEqual(self.product.extension_count, 1)
        self.assertEqual(self.product.current_price, Decimal("110.00"))

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_bid_outside_window_keeps_deadline(self):
        product = self._product(title="Not Late Yet", end_in=timedelta(minutes=10))
        original_end = product.auction_end
        place_bid(product, self.bidder, Decimal("110.00"))
        product.refresh_from_db()
        self.assertEqual(product.auction_end, original_end)
        self.assertEqual(product.extension_count, 0)

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_rejected_bid_does_not_extend(self):
        original_end = self.product.auction_end
        with self.assertRaises(BidError):
            place_bid(self.product, self.bidder, Decimal("105.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.auction_end, original_end)
        self.assertEqual(self.product.extension_count, 0)
        self.assertEqual(Bid.objects.count(), 0)

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_extension_stops_at_cap(self):
        Product.objects.filter(pk=self.product.pk).update(extension_count=2)
        self.product.refresh_from_db()
        place_bid(self.product, self.bidder, Decimal("110.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.extension_count, 3)
        first_end = self.product.auction_end

        # Cap now reached: another bid inside the window cannot extend again.
        Product.objects.filter(pk=self.product.pk).update(current_price=Decimal("110.00"))
        rival = User.objects.create_user(
            "snip_rival", password="pw12345!", role=User.Role.BIDDER
        )
        place_bid(self.product, rival, Decimal("120.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.auction_end, first_end)
        self.assertEqual(self.product.extension_count, 3)

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_seller_and_watchers_are_notified_of_extension(self):
        place_bid(self.product, self.bidder, Decimal("110.00"))
        for user in (self.seller, self.watcher):
            self.assertTrue(
                Notification.objects.filter(
                    user=user, message__icontains="Anti-sniping"
                ).exists(),
                f"{user.username} should be told about the extension",
            )

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_extended_broadcast_carries_persisted_deadline(self):
        from unittest.mock import patch

        captured = []
        with patch("bids.services.broadcast_auction", side_effect=lambda p, event: captured.append((p, event))):
            place_bid(self.product, self.bidder, Decimal("110.00"))

        self.assertEqual(len(captured), 1)
        _, event = captured[0]
        self.assertEqual(event, "extended")
        # The product handed to the broadcaster is the same one that was just
        # persisted, so what clients receive matches the database.
        self.product.refresh_from_db()
        self.assertEqual(captured[0][0].auction_end, self.product.auction_end)

    @override_settings(SNIP_WINDOW_SECONDS=60, AUCTION_EXTENSION_MINUTES=2, AUCTION_MAX_EXTENSIONS=3)
    def test_bid_status_ajax_reports_extension(self):
        place_bid(self.product, self.bidder, Decimal("110.00"))
        self.product.refresh_from_db()
        response = self.client.get(reverse("bids:status_ajax", args=[self.product.slug]))
        data = response.json()
        self.assertEqual(data["auction_end"], self.product.auction_end.isoformat())
        self.assertEqual(data["extension_count"], 1)

class StaleSnapshotTestCase(TestCase):
    """The row is re-read under lock inside place_bid(), so a bidder holding a
    stale in-memory Product can never re-validate against outdated state."""

    def setUp(self):
        self.seller = User.objects.create_user("stale_seller", password="pw12345!", role=User.Role.SELLER)
        self.bidder = User.objects.create_user("stale_bidder", password="pw12345!", role=User.Role.BIDDER)
        self.rival = User.objects.create_user("stale_rival", password="pw12345!", role=User.Role.BIDDER)
        self.category = Category.objects.create(name="Coins")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Stale Coin",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )

    def test_stale_snapshot_is_revalidated_against_fresh_price(self):
        stale = Product.objects.get(pk=self.product.pk)  # still reads 100.00
        place_bid(self.product, self.bidder, Decimal("110.00"))  # commits 110.00

        with self.assertRaises(BidError):
            place_bid(stale, self.rival, Decimal("110.00"))  # stale min said 110.00

        self.assertEqual(Bid.objects.filter(product=self.product).count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_price, Decimal("110.00"))

    def test_stale_snapshot_cannot_replay_expired_deadline(self):
        stale = Product.objects.get(pk=self.product.pk)
        Product.objects.filter(pk=self.product.pk).update(
            auction_end=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(BidError):
            place_bid(stale, self.bidder, Decimal("110.00"))
        self.assertEqual(Bid.objects.count(), 0)

    def test_stale_snapshot_cannot_extend_from_dead_object(self):
        stale = Product.objects.get(pk=self.product.pk)
        Product.objects.filter(pk=self.product.pk).update(
            auction_end=timezone.now() + timedelta(seconds=30)
        )
        # stale copy still believes an hour remains, so its own helper would
        # decline to extend; the re-read copy inside place_bid must extend.
        place_bid(stale, self.bidder, Decimal("110.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.extension_count, 1)
        self.assertGreater(
            self.product.auction_end, timezone.now() + timedelta(seconds=60)
        )


class ConcurrentBiddingTests(TransactionTestCase):
    """Parallel ``place_bid()`` calls racing on one auction.

    Runs real threads against the test database with a barrier so the bids land
    together. On PostgreSQL the ``select_for_update()`` inside place_bid makes
    the loser re-read and re-validate the committed row; this suite asserts the
    *observable invariants* (never two winners at one price, price always equals
    the highest committed bid) which must hold on any backend. Where SQLite
    cannot honour row locks, a thread may surface an OperationalError from the
    backend instead of a business rejection; that is counted as "locked" and
    still may never produce a partial/contradictory write.
    """

    def setUp(self):
        self.seller = User.objects.create_user("race_seller", password="pw12345!", role=User.Role.SELLER)
        self.category = Category.objects.create(name="Racing")
        self.bidders = [
            User.objects.create_user(f"racer{i}", password="pw12345!", role=User.Role.BIDDER)
            for i in range(3)
        ]
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Contested Lot",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )

    def _race(self, attempts):
        """Run (bidder, amount) pairs in parallel threads; returns outcomes."""
        barrier = threading.Barrier(len(attempts), timeout=20)
        results = []
        results_lock = threading.Lock()

        def worker(bidder, amount):
            try:
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    outcome = ("barrier_broken", "")
                else:
                    try:
                        place_bid(self.product, bidder, amount)
                        outcome = ("ok", "")
                    except BidError as exc:
                        outcome = ("rejected", str(exc))
                    except OperationalError as exc:
                        outcome = ("locked", str(exc))
                with results_lock:
                    results.append(outcome)
            finally:
                connection.close()  # each thread owns its connection

        threads = [
            threading.Thread(target=worker, args=(bidder, amount))
            for bidder, amount in attempts
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads), "thread hung")
        return results

    def test_simultaneous_identical_bids_commit_exactly_one(self):
        results = self._race(
            [(bidder, Decimal("110.00")) for bidder in self.bidders]
        )

        committed = Bid.objects.filter(product=self.product)
        successes = [outcome for outcome, _ in results if outcome == "ok"]
        for outcome, _ in results:
            self.assertIn(outcome, ("ok", "rejected", "locked"))

        # Never more than one identical bid may win the race, on any backend.
        self.assertLessEqual(committed.count(), 1)
        self.assertLessEqual(len(successes), 1)

        self.product.refresh_from_db()
        if committed.count() == 1:
            self.assertEqual(len(successes), 1, "one success for one committed bid")
            self.assertEqual(self.product.current_price, Decimal("110.00"))
            self.assertEqual(self.product.minimum_next_bid, Decimal("120.00"))
        else:
            # SQLite cannot hold row locks: all three writers may be locked out.
            # Nothing may have been written, and the auction must recover.
            self.assertTrue(
                all(outcome == "locked" for outcome, _ in results),
                "an empty result set may only come from backend lock-outs",
            )
            self.assertEqual(self.product.current_price, Decimal("100.00"))
            place_bid(self.product, self.bidders[0], Decimal("110.00"))
            self.product.refresh_from_db()
            self.assertEqual(self.product.current_price, Decimal("110.00"))

    def test_parallel_bids_leave_price_consistent_with_committed_bids(self):
        amounts = [Decimal("110.00"), Decimal("120.00"), Decimal("140.00")]
        results = self._race(list(zip(self.bidders, amounts, strict=True)))

        committed = list(
            Bid.objects.filter(product=self.product).values_list("amount", flat=True)
        )
        successes = [outcome for outcome, _ in results if outcome == "ok"]
        for outcome, _ in results:
            self.assertIn(outcome, ("ok", "rejected", "locked"))

        # Every reported success must correspond to a committed bid.
        self.assertEqual(len(successes), len(committed))
        # No bid outside the raced set may appear, and no duplicate prices.
        self.assertTrue(set(committed) <= set(amounts))
        self.assertEqual(len(set(committed)), len(committed))

        self.product.refresh_from_db()
        if committed:
            self.assertEqual(self.product.current_price, max(committed))
            self.assertEqual(
                self.product.minimum_next_bid, max(committed) + Decimal("10.00")
            )
        else:
            # SQLite can lock every thread out at once; then nothing may have
            # been written and the auction must be untouched.
            self.assertTrue(all(outcome == "locked" for outcome, _ in results))
            self.assertEqual(self.product.current_price, Decimal("100.00"))

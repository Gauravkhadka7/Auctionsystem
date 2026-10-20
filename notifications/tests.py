from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .broadcast import dispatch_notification, notify, serialize_notification, user_group_name
from .models import Notification

User = get_user_model()


class NotificationTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("notif_user", password="pw12345!")
        self.other = User.objects.create_user("notif_other", password="pw12345!")
        self.n1 = Notification.objects.create(user=self.user, message="First", link="/products/a/")
        self.n2 = Notification.objects.create(user=self.user, message="Second")

    def test_list_requires_login(self):
        response = self.client.get(reverse("notifications:list"))
        self.assertEqual(response.status_code, 302)

    def test_list_marks_all_as_read(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(user=self.user, is_read=False).count(), 0)

    def test_open_marks_read_and_redirects_to_link(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:open", args=[self.n1.pk]))
        self.assertRedirects(response, "/products/a/", fetch_redirect_response=False)
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)

    def test_cannot_open_another_users_notification(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("notifications:open", args=[self.n1.pk]))
        self.assertEqual(response.status_code, 404)

    def test_context_processor_exposes_unread_count(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["unread_notification_count"], 2)

    def test_long_message_is_accepted(self):
        # Outbid messages can exceed the old 255-char column; regression guard.
        message = "x" * 400
        n = Notification.objects.create(user=self.user, message=message)
        self.assertEqual(n.message, message)


class FakeChannelLayer:
    """Records group_send calls instead of touching a real channel layer."""

    def __init__(self):
        self.calls = []

    async def group_send(self, group, message):
        self.calls.append((group, message))


class NotificationDispatchTests(TestCase):
    """notify() writes the row and pushes it to the owner's private group."""

    def setUp(self):
        self.user = User.objects.create_user("dispatch_user", password="pw12345!")
        self.other = User.objects.create_user("dispatch_other", password="pw12345!")

    def test_notify_creates_row_and_pushes_to_user_group(self):
        layer = FakeChannelLayer()
        with patch("channels.layers.get_channel_layer", return_value=layer):
            notification = notify(self.user, "You've been outbid.", link="/products/x/")

        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())
        self.assertEqual(len(layer.calls), 1)
        group, message = layer.calls[0]
        self.assertEqual(group, user_group_name(self.user.pk))
        self.assertEqual(group, f"user_{self.user.pk}")
        self.assertEqual(message["type"], "notification.new")
        self.assertEqual(message["message"], "You've been outbid.")
        self.assertEqual(message["link"], "/products/x/")
        self.assertEqual(
            message["open_url"], reverse("notifications:open", args=[notification.pk])
        )
        self.assertEqual(message["unread_count"], 1)

    def test_unread_count_ignores_read_and_other_users_notifications(self):
        Notification.objects.create(user=self.user, message="old", is_read=True)
        Notification.objects.create(user=self.other, message="not mine")
        layer = FakeChannelLayer()
        with patch("channels.layers.get_channel_layer", return_value=layer):
            notify(self.user, "fresh")

        self.assertEqual(layer.calls[0][1]["unread_count"], 1)

    def test_dispatch_is_a_noop_without_a_channel_layer(self):
        notification = Notification.objects.create(user=self.user, message="offline")
        with patch("channels.layers.get_channel_layer", return_value=None):
            self.assertIsNone(dispatch_notification(notification))
        self.assertEqual(Notification.objects.filter(pk=notification.pk).count(), 1)

    def test_serialize_exposes_contract_fields(self):
        notification = Notification.objects.create(user=self.user, message="hello", link="/a/")
        payload = serialize_notification(notification)
        self.assertEqual(payload["type"], "notification.new")
        self.assertEqual(payload["id"], notification.pk)
        self.assertEqual(payload["message"], "hello")
        self.assertEqual(payload["link"], "/a/")
        self.assertEqual(payload["unread_count"], 1)

    def test_outbid_bid_triggers_a_real_time_push(self):
        from decimal import Decimal

        from django.utils import timezone

        from bids.services import place_bid
        from categories.models import Category
        from products.models import Product

        seller = User.objects.create_user(
            "dispatch_seller", password="pw12345!", role=User.Role.SELLER
        )
        now = timezone.now()
        product = Product.objects.create(
            seller=seller,
            category=Category.objects.create(name="Dispatch"),
            title="Dispatch Lot",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=1),
            status=Product.Status.LIVE,
        )
        place_bid(product, self.user, Decimal("110.00"))  # self.user takes the lead

        layer = FakeChannelLayer()
        with patch("channels.layers.get_channel_layer", return_value=layer):
            place_bid(product, self.other, Decimal("120.00"))

        groups = [group for group, _ in layer.calls]
        self.assertIn(f"auction_{product.slug}", groups, "bidders receive the new price")
        self.assertIn(
            user_group_name(self.user.pk), groups, "the outbid leader gets a bell push"
        )
        pushed = next(
            message
            for group, message in layer.calls
            if group == user_group_name(self.user.pk)
        )
        self.assertEqual(pushed["type"], "notification.new")
        self.assertIn("outbid", pushed["message"])


class NotificationWebSocketTests(TransactionTestCase):
    """The per-user socket sends a snapshot and streams new notifications."""

    def setUp(self):
        self.user = User.objects.create_user("ws_notif_user", password="pw12345!")
        self.url = "/ws/notifications/"

    def _application(self, user):
        from .consumers import NotificationConsumer

        consumer = NotificationConsumer.as_asgi()

        async def app(scope, receive, send):
            scope["user"] = user
            return await consumer(scope, receive, send)

        return app

    async def test_anonymous_connection_is_rejected(self):
        from channels.testing import WebsocketCommunicator
        from django.contrib.auth.models import AnonymousUser

        communicator = WebsocketCommunicator(
            self._application(AnonymousUser()), "/ws/notifications/"
        )
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_connect_sends_unread_snapshot(self):
        from asgiref.sync import sync_to_async
        from channels.testing import WebsocketCommunicator

        await sync_to_async(Notification.objects.create)(user=self.user, message="first")
        await sync_to_async(Notification.objects.create)(
            user=self.user, message="read one", is_read=True
        )

        communicator = WebsocketCommunicator(
            self._application(self.user), "/ws/notifications/"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        snapshot = await communicator.receive_json_from()
        self.assertEqual(snapshot["type"], "notification.snapshot")
        self.assertEqual(snapshot["unread_count"], 1)

        await communicator.disconnect()

    async def test_pushed_notification_reaches_the_client(self):
        from channels.layers import get_channel_layer
        from channels.testing import WebsocketCommunicator

        communicator = WebsocketCommunicator(
            self._application(self.user), "/ws/notifications/"
        )
        await communicator.connect()
        await communicator.receive_json_from()  # snapshot

        await get_channel_layer().group_send(
            user_group_name(self.user.pk),
            {
                "type": "notification.new",
                "id": 99,
                "message": "A late bid extended the auction.",
                "link": "/products/x/",
                "open_url": "/notifications/99/open/",
                "unread_count": 3,
            },
        )

        pushed = await communicator.receive_json_from(timeout=2)
        self.assertEqual(pushed["type"], "notification.new")
        self.assertEqual(pushed["message"], "A late bid extended the auction.")
        self.assertEqual(pushed["unread_count"], 3)

        await communicator.disconnect()

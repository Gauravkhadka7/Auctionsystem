from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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

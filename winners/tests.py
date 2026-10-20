import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from categories.models import Category
from notifications.models import Notification
from payments.models import Payment
from products.models import Product

from .models import Winner
from .services import VerificationError, reject_winner_verification, verify_winner

User = get_user_model()


def make_document(name="citizenship.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "green").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class WinnerTestBase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            "win_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.winner_user = User.objects.create_user(
            "win_bidder", password="pw12345!", role=User.Role.BIDDER
        )
        self.other_bidder = User.objects.create_user(
            "win_other", password="pw12345!", role=User.Role.BIDDER
        )
        self.admin = User.objects.create_user(
            "win_admin", password="pw12345!", role=User.Role.ADMIN
        )
        self.category = Category.objects.create(name="Wins")
        self.product = self.make_closed_product("Trophy Lot")
        self.winner = Winner.objects.create(
            product=self.product,
            bidder=self.winner_user,
            winning_price=Decimal("150.00"),
        )

    def make_closed_product(self, title):
        now = timezone.now()
        return Product.objects.create(
            seller=self.seller,
            category=self.category,
            title=title,
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=3),
            auction_end=now - timedelta(hours=1),
            status=Product.Status.CLOSED,
        )


class WinnerVisibilityTests(WinnerTestBase):
    def test_public_list_shows_verified_winner(self):
        self.winner.is_payment_verified = True
        self.winner.save(update_fields=["is_payment_verified"])
        response = self.client.get(reverse("winners:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trophy Lot")

    def test_public_list_hides_unverified_winner(self):
        response = self.client.get(reverse("winners:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Trophy Lot")

    def test_public_list_shows_delivered_winner(self):
        self.winner.is_delivered = True
        self.winner.save(update_fields=["is_delivered"])
        response = self.client.get(reverse("winners:list"))
        self.assertContains(response, "Trophy Lot")

    def test_my_wins_requires_bidder_role(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("winners:my_wins"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard_redirect"))

    def test_my_wins_lists_only_own_wins(self):
        other_product = self.make_closed_product("Someone Else Lot")
        Winner.objects.create(
            product=other_product, bidder=self.other_bidder, winning_price=Decimal("200.00")
        )
        self.client.force_login(self.winner_user)
        response = self.client.get(reverse("winners:my_wins"))
        self.assertContains(response, "Trophy Lot")
        self.assertNotContains(response, "Someone Else Lot")

    def test_owner_can_open_winner_detail(self):
        self.client.force_login(self.winner_user)
        response = self.client.get(reverse("winners:detail", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "winners/winner_detail.html")

    def test_admin_can_open_any_winner_detail(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("winners:detail", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 200)

    def test_other_bidder_is_denied(self):
        self.client.force_login(self.other_bidder)
        response = self.client.get(reverse("winners:detail", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard_redirect"))

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("winners:detail", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))


class WinnerVerificationServiceTests(WinnerTestBase):
    def test_verify_requires_submitted_documents(self):
        with self.assertRaises(VerificationError):
            verify_winner(self.winner)

    def test_verify_marks_winner_kyc_verified_and_notifies(self):
        self.winner.is_verification_submitted = True
        self.winner.save(update_fields=["is_verification_submitted"])

        verify_winner(self.winner)

        self.winner_user.refresh_from_db()
        self.assertTrue(self.winner_user.is_kyc_verified)
        self.assertTrue(
            Notification.objects.filter(
                user=self.winner_user, message__icontains="approved"
            ).exists()
        )

    def test_reject_resets_submission_and_notifies(self):
        self.winner.is_verification_submitted = True
        self.winner.save(update_fields=["is_verification_submitted"])

        reject_winner_verification(self.winner, reason="Blurry document.")

        self.winner.refresh_from_db()
        self.assertFalse(self.winner.is_verification_submitted)
        self.assertFalse(self.winner.bidder.is_kyc_verified)
        self.assertTrue(
            Notification.objects.filter(
                user=self.winner_user, message__icontains="Blurry document."
            ).exists()
        )

    def test_reject_without_submission_raises(self):
        with self.assertRaises(VerificationError):
            reject_winner_verification(self.winner)

    def test_payment_verification_flag_is_independent_of_kyc(self):
        self.winner.is_verification_submitted = True
        self.winner.save(update_fields=["is_verification_submitted"])
        verify_winner(self.winner)
        self.winner.refresh_from_db()
        self.assertFalse(self.winner.is_payment_verified)


class SubmitVerificationViewTests(WinnerTestBase):
    def _payload(self):
        return {
            "citizenship_number": "12-345-678",
            "citizenship_document": make_document(),
            "bank_name": "Nabil",
            "bank_account_number": "000111222",
            "bank_account_holder": "Win Bidder",
            "esewa_number": "9800000000",
            "khalti_number": "9811111111",
        }

    def test_bidder_submits_documents_and_flag_is_set(self):
        self.client.force_login(self.winner_user)
        response = self.client.post(
            reverse("winners:submit_verification", args=[self.winner.pk]), self._payload()
        )
        self.assertRedirects(response, reverse("winners:detail", args=[self.winner.pk]))
        self.winner.refresh_from_db()
        self.assertTrue(self.winner.is_verification_submitted)
        self.assertEqual(self.winner.bidder.profile.citizenship_number, "12-345-678")

    def test_get_renders_the_verification_form(self):
        self.client.force_login(self.winner_user)
        response = self.client.get(
            reverse("winners:submit_verification", args=[self.winner.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "winners/submit_verification.html")

    def test_other_bidder_cannot_submit_for_someone_else(self):
        self.client.force_login(self.other_bidder)
        response = self.client.get(reverse("winners:submit_verification", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 404)

    def test_seller_is_redirected_away(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("winners:submit_verification", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 302)

    def test_verified_payment_is_needed_to_appear_in_public_list(self):
        Payment.objects.create(
            winner=self.winner,
            payer=self.winner_user,
            method=Payment.Method.ESEWA,
            amount=Decimal("150.00"),
            status=Payment.Status.PENDING,
        )
        response = self.client.get(reverse("winners:list"))
        self.assertNotContains(response, "Trophy Lot")

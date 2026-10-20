from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from categories.models import Category
from notifications.models import Notification
from products.models import Product
from winners.models import Winner

from .forms import PaymentForm
from .models import Payment
from .services import PaymentError, reject_payment, verify_payment

User = get_user_model()


class PaymentTestBase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            "pay_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            "pay_bidder", password="pw12345!", role=User.Role.BIDDER
        )
        self.other_bidder = User.objects.create_user(
            "pay_other", password="pw12345!", role=User.Role.BIDDER
        )
        self.admin = User.objects.create_user(
            "pay_admin", password="pw12345!", role=User.Role.ADMIN
        )
        self.category = Category.objects.create(name="Payments")
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            title="Paid Lot",
            description="d",
            main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"),
            bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=3),
            auction_end=now - timedelta(hours=1),
            status=Product.Status.CLOSED,
        )
        self.winner = Winner.objects.create(
            product=self.product,
            bidder=self.bidder,
            winning_price=Decimal("150.00"),
        )

    def make_payment(self, amount=Decimal("150.00"), status=Payment.Status.PENDING):
        return Payment.objects.create(
            winner=self.winner,
            payer=self.bidder,
            method=Payment.Method.ESEWA,
            transaction_id="TXN-1",
            amount=amount,
            status=status,
        )


class PaymentFormTests(PaymentTestBase):
    def test_zero_amount_is_rejected(self):
        form = PaymentForm(
            data={"method": Payment.Method.ESEWA, "transaction_id": "T", "amount": "0.00"},
            winner=self.winner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_negative_amount_is_rejected(self):
        form = PaymentForm(
            data={"method": Payment.Method.ESEWA, "transaction_id": "T", "amount": "-25.00"},
            winner=self.winner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_amount_above_winning_price_is_rejected(self):
        form = PaymentForm(
            data={"method": Payment.Method.ESEWA, "transaction_id": "T", "amount": "500.00"},
            winner=self.winner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_amount_equal_to_winning_price_is_accepted(self):
        form = PaymentForm(
            data={"method": Payment.Method.ESEWA, "transaction_id": "T", "amount": "150.00"},
            winner=self.winner,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_partial_amount_below_winning_price_is_allowed(self):
        form = PaymentForm(
            data={"method": Payment.Method.ESEWA, "transaction_id": "T", "amount": "75.00"},
            winner=self.winner,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_amount_without_winner_context_is_not_capped(self):
        form = PaymentForm(
            data={"method": Payment.Method.KHALTI, "transaction_id": "T", "amount": "9999.00"}
        )
        self.assertTrue(form.is_valid(), form.errors)


class SubmitPaymentViewTests(PaymentTestBase):
    def test_bidder_submits_pending_payment(self):
        self.client.force_login(self.bidder)
        response = self.client.post(
            reverse("payments:submit", args=[self.winner.pk]),
            {"method": Payment.Method.KHALTI, "transaction_id": "AB12", "amount": "150.00"},
        )
        self.assertRedirects(response, reverse("winners:detail", args=[self.winner.pk]))
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.payer, self.bidder)
        self.assertEqual(payment.winner, self.winner)

    def test_get_prefills_the_winning_price(self):
        self.client.force_login(self.bidder)
        response = self.client.get(reverse("payments:submit", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="150.00"')

    def test_amount_above_winning_price_is_not_saved(self):
        self.client.force_login(self.bidder)
        self.client.post(
            reverse("payments:submit", args=[self.winner.pk]),
            {"method": Payment.Method.KHALTI, "transaction_id": "AB12", "amount": "9999.00"},
        )
        self.assertEqual(Payment.objects.count(), 0)

    def test_other_bidder_cannot_pay_for_someone_elses_win(self):
        self.client.force_login(self.other_bidder)
        response = self.client.get(reverse("payments:submit", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 404)

    def test_seller_cannot_reach_the_payment_form(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("payments:submit", args=[self.winner.pk]))
        self.assertEqual(response.status_code, 302)

    def test_submission_does_not_verify_itself(self):
        self.client.force_login(self.bidder)
        self.client.post(
            reverse("payments:submit", args=[self.winner.pk]),
            {"method": Payment.Method.KHALTI, "transaction_id": "AB12", "amount": "150.00"},
        )
        self.winner.refresh_from_db()
        self.assertFalse(self.winner.is_payment_verified)


class PaymentVerificationServiceTests(PaymentTestBase):
    def test_verify_marks_payment_and_winner(self):
        payment = self.make_payment()
        returned = verify_payment(payment)
        payment.refresh_from_db()
        self.winner.refresh_from_db()

        self.assertEqual(returned.status, Payment.Status.VERIFIED)
        self.assertEqual(payment.status, Payment.Status.VERIFIED)
        self.assertIsNotNone(payment.verified_at)
        self.assertTrue(self.winner.is_payment_verified)
        self.assertTrue(
            Notification.objects.filter(user=self.bidder, message__icontains="verified").exists()
        )

    def test_verify_only_accepts_pending_payments(self):
        payment = self.make_payment(status=Payment.Status.VERIFIED)
        with self.assertRaises(PaymentError):
            verify_payment(payment)

    def test_verify_cannot_run_twice(self):
        payment = self.make_payment()
        verify_payment(payment)
        with self.assertRaises(PaymentError):
            verify_payment(payment)
        self.assertEqual(
            Notification.objects.filter(user=self.bidder, message__icontains="verified").count(),
            1,
            "a payment must not be processed twice",
        )

    def test_reject_marks_payment_and_keeps_winner_unverified(self):
        payment = self.make_payment()
        reject_payment(payment, reason="Reference number mismatch.")
        payment.refresh_from_db()
        self.winner.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.REJECTED)
        self.assertFalse(self.winner.is_payment_verified)
        self.assertTrue(
            Notification.objects.filter(
                user=self.bidder, message__icontains="Reference number mismatch."
            ).exists()
        )

    def test_reject_only_accepts_pending_payments(self):
        payment = self.make_payment()
        reject_payment(payment)
        with self.assertRaises(PaymentError):
            reject_payment(payment)

    def test_rejecting_one_payment_leaves_other_payments_untouched(self):
        first = self.make_payment(amount=Decimal("50.00"))
        second = self.make_payment(amount=Decimal("100.00"))
        reject_payment(first)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Payment.Status.REJECTED)
        self.assertEqual(second.status, Payment.Status.PENDING)

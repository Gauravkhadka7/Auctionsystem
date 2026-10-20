import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from bids.models import Bid
from categories.models import Category
from notifications.models import Notification
from payments.models import Payment
from payments.services import verify_payment
from products.models import Product
from products.services import approve_product
from winners.models import Winner
from winners.services import verify_winner

from .views import seller_analytics

User = get_user_model()


def make_image(name="item.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def make_product(seller, category, title, status=Product.Status.CLOSED, **kwargs):
    now = timezone.now()
    return Product.objects.create(
        seller=seller,
        category=category,
        title=title,
        description="d",
        main_image="products/main/x.jpg",
        starting_price=kwargs.pop("starting_price", Decimal("100.00")),
        bid_increment=Decimal("10.00"),
        reserve_price=kwargs.pop("reserve_price", None),
        auction_start=now - timedelta(hours=3),
        auction_end=now - timedelta(hours=1),
        status=status,
        **kwargs,
    )


class SellerAnalyticsTests(TestCase):
    """Revenue rules: verified payments only, never added to hammer prices, and
    never multiplied by one-to-many joins."""

    def setUp(self):
        self.seller = User.objects.create_user(
            "an_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.other_seller = User.objects.create_user(
            "an_other", password="pw12345!", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            "an_bidder", password="pw12345!", role=User.Role.BIDDER
        )
        self.category = Category.objects.create(name="Analytics")
        self.product = make_product(self.seller, self.category, "Seller Lot")

    def add_bid(self, product, amount):
        return Bid.objects.create(product=product, bidder=self.bidder, amount=Decimal(amount))

    def add_settled_winner(self, product, winning_price, amount, status=Payment.Status.VERIFIED):
        winner = Winner.objects.create(
            product=product, bidder=self.bidder, winning_price=Decimal(winning_price)
        )
        if status == Payment.Status.VERIFIED:
            winner.is_payment_verified = True
            winner.save(update_fields=["is_payment_verified"])
        payment = Payment.objects.create(
            winner=winner,
            payer=self.bidder,
            method=Payment.Method.ESEWA,
            amount=Decimal(amount),
            status=status,
        )
        return winner, payment

    def test_metrics_are_scoped_to_the_seller(self):
        self.add_bid(self.product, "110.00")
        self.add_bid(self.product, "120.00")

        rival_product = make_product(self.other_seller, self.category, "Rival Lot")
        for amount in ("130.00", "140.00", "150.00"):
            self.add_bid(rival_product, amount)
        self.add_settled_winner(rival_product, "150.00", "150.00")

        analytics = seller_analytics(self.seller)
        self.assertEqual(analytics["total_bids"], 2)
        self.assertEqual(analytics["total_listings"], 1)
        self.assertEqual(analytics["verified_revenue"], Decimal("0.00"))
        self.assertEqual(analytics["settled_count"], 0)

    def test_only_verified_payments_count_as_revenue(self):
        pending_product = make_product(self.seller, self.category, "Pending Pay")
        rejected_product = make_product(self.seller, self.category, "Rejected Pay")
        self.add_settled_winner(self.product, "150.00", "150.00")
        self.add_settled_winner(pending_product, "200.00", "200.00", Payment.Status.PENDING)
        self.add_settled_winner(rejected_product, "300.00", "300.00", Payment.Status.REJECTED)

        analytics = seller_analytics(self.seller)
        self.assertEqual(analytics["verified_revenue"], Decimal("150.00"))
        self.assertEqual(analytics["pending_revenue"], Decimal("200.00"))
        self.assertEqual(analytics["settled_count"], 1)
        self.assertEqual(analytics["settled_winning_value"], Decimal("150.00"))

    def test_partial_payments_do_not_inflate_hammer_value(self):
        winner, first = self.add_settled_winner(self.product, "150.00", "50.00")
        Payment.objects.create(
            winner=winner,
            payer=self.bidder,
            method=Payment.Method.KHALTI,
            amount=Decimal("100.00"),
            status=Payment.Status.VERIFIED,
        )

        analytics = seller_analytics(self.seller)
        self.assertEqual(analytics["verified_revenue"], Decimal("150.00"))
        self.assertEqual(analytics["settled_count"], 1)
        self.assertEqual(analytics["settled_winning_value"], Decimal("150.00"))

    def test_views_are_summed_across_listings(self):
        Product.objects.filter(pk=self.product.pk).update(view_count=3)
        make_product(self.seller, self.category, "Second Lot", view_count=4)

        analytics = seller_analytics(self.seller)
        self.assertEqual(analytics["total_views"], 7)
        self.assertEqual(analytics["total_listings"], 2)

    def test_category_breakdown_handles_categories_without_activity(self):
        quiet_category = Category.objects.create(name="Quiet Cat")
        self.add_bid(self.product, "110.00")
        make_product(self.seller, quiet_category, "Quiet Lot")

        analytics = seller_analytics(self.seller)
        rows = {row["category"].pk: row for row in analytics["category_rows"]}

        self.assertEqual(set(rows), {self.category.pk, quiet_category.pk})
        self.assertEqual(rows[self.category.pk]["bids"], 1)
        self.assertEqual(rows[self.category.pk]["bids_pct"], 100)
        self.assertEqual(rows[quiet_category.pk]["bids"], 0)
        self.assertEqual(rows[quiet_category.pk]["revenue"], Decimal("0.00"))
        self.assertEqual(rows[quiet_category.pk]["bids_pct"], 0)

    def test_revenue_by_category_uses_verified_payments(self):
        self.add_settled_winner(self.product, "150.00", "150.00")

        analytics = seller_analytics(self.seller)
        row = next(r for r in analytics["category_rows"] if r["category"].pk == self.category.pk)
        self.assertEqual(row["revenue"], Decimal("150.00"))
        self.assertEqual(row["payments"], 1)
        self.assertEqual(row["revenue_pct"], 100)
        self.assertEqual(analytics["total_revenue_by_category"], Decimal("150.00"))

    def test_seller_without_listings_gets_zeroed_metrics(self):
        fresh = User.objects.create_user(
            "an_fresh", password="pw12345!", role=User.Role.SELLER
        )
        analytics = seller_analytics(fresh)
        self.assertEqual(analytics["total_listings"], 0)
        self.assertEqual(analytics["total_bids"], 0)
        self.assertEqual(analytics["total_views"], 0)
        self.assertEqual(analytics["verified_revenue"], Decimal("0.00"))
        self.assertEqual(analytics["settled_winning_value"], Decimal("0.00"))
        self.assertEqual(analytics["category_rows"], [])


class SellerDashboardViewTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            "dash_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            "dash_bidder", password="pw12345!", role=User.Role.BIDDER
        )
        self.category = Category.objects.create(name="Dash")
        self.url = reverse("core:seller_dashboard")

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_bidder_is_redirected_to_dashboard(self):
        self.client.force_login(self.bidder)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard_redirect"))

    def test_dashboard_renders_analytics_section(self):
        make_product(self.seller, self.category, "Dash Lot", view_count=5)
        self.client.force_login(self.seller)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/seller_dashboard.html")
        analytics = response.context["analytics"]
        self.assertEqual(analytics["total_listings"], 1)
        self.assertEqual(analytics["total_views"], 5)
        self.assertContains(response, "Seller Analytics")
        self.assertContains(response, "Verified revenue")

    def test_dashboard_without_listings_shows_empty_state(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No listings yet")


class EndToEndAuctionWorkflowTests(TestCase):
    """One test walks the whole documented lifecycle: list -> approve -> live ->
    bid -> close & crown a winner -> verify identity -> pay -> admin verifies ->
    seller analytics."""

    def setUp(self):
        self.seller = User.objects.create_user(
            "e2e_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            "e2e_bidder", password="pw12345!", role=User.Role.BIDDER
        )
        self.rival = User.objects.create_user(
            "e2e_rival", password="pw12345!", role=User.Role.BIDDER
        )
        self.category = Category.objects.create(name="E2E")

    def _listing_payload(self):
        now = timezone.now()
        # datetime-local inputs are interpreted in the project's local timezone,
        # so format local times or the start drifts into the past.
        start = timezone.localtime(now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        end = timezone.localtime(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        return {
            "title": "End To End Lot",
            "category": self.category.pk,
            "subcategory": "",
            "brand": "LotHouse",
            "condition": Product.Condition.NEW,
            "description": "Full lifecycle lot.",
            "starting_price": "100.00",
            "reserve_price": "120.00",
            "bid_increment": "10.00",
            "auction_start": start,
            "auction_end": end,
            "delivery_info": "Pickup in Kathmandu.",
            "main_image": make_image("e2e.png"),
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
            "specifications-0-value": "Steel",
        }

    def _verification_payload(self):
        return {
            "citizenship_number": "12-345-678",
            "citizenship_document": make_image("e2e_doc.png"),
            "bank_name": "Nabil",
            "bank_account_number": "000111222",
            "bank_account_holder": "End To End",
            "esewa_number": "9800000000",
            "khalti_number": "9811111111",
        }

    def test_listing_to_payout_workflow(self):
        # 1. The seller lists the item; it waits for moderation.
        self.client.force_login(self.seller)
        response = self.client.post(reverse("products:product_create"), self._listing_payload())
        self.assertRedirects(response, reverse("products:my_products"))
        product = Product.objects.get()
        self.assertEqual(product.status, Product.Status.PENDING)

        # 2. An administrator approves it.
        approve_product(product)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.UPCOMING)

        # 3. Its start time arrives and the scheduled job makes it live.
        Product.objects.filter(pk=product.pk).update(
            auction_start=timezone.now() - timedelta(minutes=1)
        )
        call_command("close_expired_auctions", stdout=io.StringIO())
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.LIVE)

        # 4. Two bidders fight it out through the no-JS HTTP fallback, and one
        #    of them opens the lot page (which counts a view).
        self.client.force_login(self.bidder)
        self.client.get(product.get_absolute_url())
        self.client.post(reverse("bids:place", args=[product.slug]), {"amount": "110.00"})
        self.client.force_login(self.rival)
        self.client.post(reverse("bids:place", args=[product.slug]), {"amount": "130.00"})
        product.refresh_from_db()
        self.assertEqual(product.current_price, Decimal("130.00"))
        self.assertEqual(product.total_bids, 2)
        self.assertTrue(
            Notification.objects.filter(user=self.bidder, message__icontains="outbid").exists()
        )

        # 5. The clock runs out; the scheduled job closes it and crowns a winner.
        Product.objects.filter(pk=product.pk).update(
            auction_end=timezone.now() - timedelta(seconds=1)
        )
        call_command("close_expired_auctions", stdout=io.StringIO())
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.CLOSED)
        winner = Winner.objects.get(product=product)
        self.assertEqual(winner.bidder, self.rival)
        self.assertEqual(winner.winning_price, Decimal("130.00"))

        # 6. The winner submits KYC documents.
        self.client.force_login(self.rival)
        response = self.client.post(
            reverse("winners:submit_verification", args=[winner.pk]),
            self._verification_payload(),
        )
        self.assertRedirects(response, reverse("winners:detail", args=[winner.pk]))
        winner.refresh_from_db()
        self.assertTrue(winner.is_verification_submitted)
        self.assertFalse(winner.bidder.is_kyc_verified)

        # 7. An administrator confirms them.
        verify_winner(winner)
        winner.bidder.refresh_from_db()
        self.assertTrue(winner.bidder.is_kyc_verified)

        # 8. The winner pays; nothing is "verified" until an admin says so.
        response = self.client.post(
            reverse("payments:submit", args=[winner.pk]),
            {
                "method": Payment.Method.ESEWA,
                "transaction_id": "TXN-E2E-1",
                "amount": str(winner.winning_price),
            },
        )
        self.assertRedirects(response, reverse("winners:detail", args=[winner.pk]))
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.payer, self.rival)
        winner.refresh_from_db()
        self.assertFalse(winner.is_payment_verified)

        # 9. Admin verification settles the lot and it appears publicly.
        verify_payment(payment)
        payment.refresh_from_db()
        winner.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.VERIFIED)
        self.assertTrue(winner.is_payment_verified)
        self.assertContains(self.client.get(reverse("winners:list")), "End To End Lot")

        # 10. The seller's analytics reflect exactly one settled sale.
        analytics = seller_analytics(self.seller)
        self.assertEqual(analytics["total_bids"], 2)
        self.assertEqual(analytics["settled_count"], 1)
        self.assertEqual(analytics["verified_revenue"], Decimal("130.00"))
        self.assertEqual(analytics["settled_winning_value"], Decimal("130.00"))
        self.assertEqual(analytics["total_views"], 1)

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bids.models import Bid
from categories.models import Category
from payments.models import Payment
from products.models import Product
from winners.models import Winner

User = get_user_model()


class DashboardTestBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "admin_user", password="Admin@12345", role=User.Role.ADMIN
        )
        self.seller = User.objects.create_user(
            "seller_user", password="Seller@12345", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            "bidder_user", password="Bidder@12345", role=User.Role.BIDDER
        )
        self.category = Category.objects.create(name="Electronics")

        now = timezone.now()
        self.pending = Product.objects.create(
            seller=self.seller, category=self.category, title="Pending Lot",
            description="d", main_image="products/main/x.jpg",
            starting_price=Decimal("100.00"), bid_increment=Decimal("10.00"),
            auction_start=now + timedelta(days=1), auction_end=now + timedelta(days=3),
            status=Product.Status.PENDING,
        )
        self.live = Product.objects.create(
            seller=self.seller, category=self.category, title="Live Lot",
            description="d", main_image="products/main/x.jpg",
            starting_price=Decimal("200.00"), bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(hours=1), auction_end=now + timedelta(days=2),
            status=Product.Status.LIVE,
        )
        self.closed = Product.objects.create(
            seller=self.seller, category=self.category, title="Closed Lot",
            description="d", main_image="products/main/x.jpg",
            starting_price=Decimal("300.00"), bid_increment=Decimal("10.00"),
            auction_start=now - timedelta(days=5), auction_end=now - timedelta(days=1),
            status=Product.Status.CLOSED,
        )
        Bid.objects.create(product=self.live, bidder=self.bidder, amount=Decimal("210.00"))
        self.winner = Winner.objects.create(
            product=self.closed, bidder=self.bidder, winning_price=Decimal("300.00")
        )
        self.payment = Payment.objects.create(
            winner=self.winner, payer=self.bidder, method=Payment.Method.ESEWA,
            transaction_id="TXN123", amount=Decimal("300.00"),
            status=Payment.Status.PENDING,
        )


class AdminAccessTests(DashboardTestBase):
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_seller_cannot_access_admin_dashboard(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("dashboard:overview"))
        self.assertRedirects(response, reverse("core:dashboard_redirect"), fetch_redirect_response=False)

    def test_bidder_cannot_access_admin_dashboard(self):
        self.client.force_login(self.bidder)
        response = self.client.get(reverse("dashboard:payments"))
        self.assertRedirects(response, reverse("core:dashboard_redirect"), fetch_redirect_response=False)

    def test_admin_can_access_overview(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/overview.html")

    def test_non_admin_cannot_post_verification_actions(self):
        self.client.force_login(self.bidder)
        response = self.client.post(reverse("dashboard:payment_verify", args=[self.payment.pk]))
        self.assertRedirects(response, reverse("core:dashboard_redirect"), fetch_redirect_response=False)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_dashboard_redirect_sends_admin_to_new_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:dashboard_redirect"))
        self.assertRedirects(response, reverse("dashboard:overview"))


class OverviewStatsTests(DashboardTestBase):
    def test_overview_statistics_match_database(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:overview"))
        stats = response.context["stats"]

        self.assertEqual(stats["users"]["total"], 3)
        self.assertEqual(stats["users"]["sellers"], 1)
        self.assertEqual(stats["users"]["bidders"], 1)
        self.assertEqual(stats["products"]["total"], 3)
        self.assertEqual(stats["products"]["pending"], 1)
        self.assertEqual(stats["products"]["live"], 1)
        self.assertEqual(stats["products"]["closed"], 1)
        self.assertEqual(stats["total_bids"], 1)
        self.assertEqual(stats["winners"]["total"], 1)
        self.assertEqual(stats["payments"]["pending"], 1)
        self.assertIsNone(stats["platform_revenue"])

    def test_overview_on_empty_database_renders(self):
        Product.objects.all().delete()
        Winner.objects.all().delete()
        Payment.objects.all().delete()
        Bid.objects.all().delete()
        User.objects.all().delete()
        admin = User.objects.create_user("admin2", password="x", role=User.Role.ADMIN)
        self.client.force_login(admin)
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["products"]["total"], 0)


class UserManagementTests(DashboardTestBase):
    def test_user_list_search(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:users"), {"q": "seller_user"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_seller_list_only_shows_sellers(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:sellers"))
        self.assertEqual([u.role for u in response.context["page_obj"]], [User.Role.SELLER])

    def test_toggle_active_deactivates_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("dashboard:user_toggle_active", args=[self.bidder.pk]))
        self.assertRedirects(response, reverse("dashboard:user_detail", args=[self.bidder.pk]))
        self.bidder.refresh_from_db()
        self.assertFalse(self.bidder.is_active)

    def test_admin_cannot_deactivate_self(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:user_toggle_active", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_user_detail_never_exposes_password_hash(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:user_detail", args=[self.bidder.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.bidder.password)


class ProductModerationTests(DashboardTestBase):
    def test_approve_pending_listing_moves_to_upcoming(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:product_approve", args=[self.pending.pk]))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Product.Status.UPCOMING)

    def test_approve_is_idempotent_safe(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:product_approve", args=[self.pending.pk]))
        self.client.post(reverse("dashboard:product_approve", args=[self.pending.pk]))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Product.Status.UPCOMING)

    def test_reject_pending_listing_sets_remarks(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:product_reject", args=[self.pending.pk]), {"reason": "Bad photos"})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Product.Status.REJECTED)
        self.assertEqual(self.pending.admin_remarks, "Bad photos")

    def test_product_list_filter_by_status(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:products"), {"status": "LIVE"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_product_detail_without_image_renders(self):
        self.pending.main_image = ""
        self.pending.save(update_fields=["main_image"])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:product_detail", args=[self.pending.pk]))
        self.assertEqual(response.status_code, 200)

    def test_product_management_requires_post(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:product_approve", args=[self.pending.pk]))
        self.assertEqual(response.status_code, 405)


class BidHistoryTests(DashboardTestBase):
    def test_bid_list_is_read_only_and_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:bids"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)


class WinnerVerificationTests(DashboardTestBase):
    def test_verify_requires_submission(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:winner_verify", args=[self.winner.pk]))
        self.bidder.refresh_from_db()
        self.assertFalse(self.bidder.is_kyc_verified)

    def test_verify_marks_bidder_kyc_verified(self):
        self.winner.is_verification_submitted = True
        self.winner.save(update_fields=["is_verification_submitted"])
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:winner_verify", args=[self.winner.pk]))
        self.bidder.refresh_from_db()
        self.assertTrue(self.bidder.is_kyc_verified)

    def test_reject_resets_submission(self):
        self.winner.is_verification_submitted = True
        self.winner.save(update_fields=["is_verification_submitted"])
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:winner_reject", args=[self.winner.pk]), {"reason": "Blurry"})
        self.winner.refresh_from_db()
        self.assertFalse(self.winner.is_verification_submitted)


class PaymentVerificationTests(DashboardTestBase):
    def test_verify_pending_payment(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:payment_verify", args=[self.payment.pk]))
        self.payment.refresh_from_db()
        self.winner.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.VERIFIED)
        self.assertIsNotNone(self.payment.verified_at)
        self.assertTrue(self.winner.is_payment_verified)

    def test_duplicate_verification_is_prevented(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:payment_verify", args=[self.payment.pk]))
        self.payment.refresh_from_db()
        first_stamp = self.payment.verified_at

        response = self.client.post(
            reverse("dashboard:payment_verify", args=[self.payment.pk]), follow=True
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.VERIFIED)
        self.assertEqual(self.payment.verified_at, first_stamp)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("pending" in m.lower() for m in messages))

    def test_payment_list_filter_by_status(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:payments"), {"status": "PENDING"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)


class PaginationTests(DashboardTestBase):
    def test_user_list_paginates(self):
        for i in range(25):
            User.objects.create_user(f"bulk_{i}", password="x", role=User.Role.BIDDER)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:users"))
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)


class ReportsAndActivityTests(DashboardTestBase):
    def test_reports_page_renders_with_charts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:reports"))
        self.assertEqual(response.status_code, 200)
        charts = response.context["charts"]
        self.assertIn("registrationTrend", charts)
        self.assertIn("auctionsByStatus", charts)

    def test_activity_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:activity"))
        self.assertEqual(response.status_code, 200)

    def test_global_search_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:search"), {"q": "Lot"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["products"]), 3)

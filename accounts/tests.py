import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from unittest import mock

from .models import EmailOTP
from .tokens import email_verification_token

User = get_user_model()


class LoginBackendTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bidder1",
            email="bidder1@example.com",
            password="Bidder@12345",
            role=User.Role.BIDDER,
            is_email_verified=True,
        )

    def test_login_with_username(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "bidder1", "password": "Bidder@12345"},
        )
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )

    def test_login_with_email(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.email, "password": "Bidder@12345"},
        )
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )

    def test_login_wrong_password_shows_error(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "bidder1", "password": "wrongpass"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct")

    def test_login_blocked_before_verification(self):
        self.user.is_email_verified = False
        self.user.save(update_fields=["is_email_verified"])
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "bidder1", "password": "Bidder@12345"},
        )
        self.assertEqual(response.status_code, 200)
        codes = [
            err.code
            for err in response.context["form"].errors.as_data().get("__all__", [])
        ]
        self.assertIn("unverified", codes)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_user_can_login_without_email_verification(self):
        staff = User.objects.create_user(
            username="ops", email="ops@example.com", password="Ops@12345", is_staff=True
        )
        self.assertFalse(staff.is_email_verified)
        response = self.client.post(
            reverse("accounts:login"), {"username": "ops", "password": "Ops@12345"}
        )
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )


class RegisterTests(TestCase):
    def setUp(self):
        cache.clear()

    def _register(
        self, username="newuser", email="newuser@example.com", role="BIDDER", follow=False
    ):
        return self.client.post(reverse("accounts:register"), {
            "first_name": "Test",
            "last_name": "User",
            "username": username,
            "email": email,
            "mobile_number": "9800000000",
            "role": role,
            "citizenship_number": "123",
            "address": "Kathmandu",
            "password1": "StrongPass@123",
            "password2": "StrongPass@123",
            "agree_terms": "on",
        }, follow=follow)

    def _token_url(self, user):
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)
        return reverse(
            "accounts:verify_email_token", kwargs={"uidb64": uidb64, "token": token}
        )

    # --- registration -----------------------------------------------------

    def test_successful_registration(self):
        response = self._register()
        user = User.objects.get(username="newuser")
        self.assertRedirects(response, reverse("accounts:verify_email_sent"))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_email_verified)
        self.assertFalse(user.is_kyc_verified)
        self.assertEqual(user.role, User.Role.BIDDER)
        self.assertTrue(user.check_password("StrongPass@123"))

    def test_registration_sends_email_to_correct_recipient(self):
        self._register()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["newuser@example.com"])
        self.assertIn("verify", message.subject.lower())
        self.assertTrue(any(part[1] == "text/html" for part in message.alternatives))
        self.assertIn("verify-email", message.body)

    def test_password_is_hashed(self):
        self._register()
        user = User.objects.get(username="newuser")
        self.assertNotEqual(user.password, "StrongPass@123")
        self.assertTrue(user.password.startswith("pbkdf2_"))

    def test_duplicate_email_rejected(self):
        User.objects.create_user(
            username="existing", email="taken@example.com", password="Pass@12345"
        )
        response = self._register(email="taken@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "email",
            "An account with this email already exists.",
        )

    def test_duplicate_email_is_case_insensitive(self):
        User.objects.create_user(
            username="existing", email="Taken@Example.com", password="Pass@12345"
        )
        response = self._register(email="taken@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "email",
            "An account with this email already exists.",
        )

    def test_duplicate_username_rejected(self):
        User.objects.create_user(
            username="newuser", email="other@example.com", password="Pass@12345"
        )
        response = self._register()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_cannot_self_register_as_admin(self):
        response = self._register(role="ADMIN")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertFormError(
            response.context["form"], "role",
            "Select a valid choice. ADMIN is not one of the available choices.",
        )

    def test_email_delivery_failure_still_creates_account(self):
        with mock.patch(
            "accounts.emails.EmailMultiAlternatives.send",
            side_effect=OSError("smtp down"),
        ):
            response = self._register(follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="newuser").exists())
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("couldn't send" in m for m in messages))

    # --- token verification ----------------------------------------------

    def test_successful_verification_via_token(self):
        self._register()
        user = User.objects.get(username="newuser")
        response = self.client.get(self._token_url(user))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/verify_email_success.html")
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertIn("_auth_user_id", self.client.session)

    def test_invalid_token_is_rejected(self):
        self._register()
        user = User.objects.get(username="newuser")
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        url = reverse(
            "accounts:verify_email_token",
            kwargs={"uidb64": uidb64, "token": "invalid-token-123"},
        )
        response = self.client.get(url)
        self.assertTemplateUsed(response, "accounts/verify_email_invalid.html")
        user.refresh_from_db()
        self.assertFalse(user.is_email_verified)

    def test_expired_token_is_rejected(self):
        self._register()
        user = User.objects.get(username="newuser")
        url = self._token_url(user)
        with override_settings(EMAIL_VERIFICATION_TIMEOUT=-1):
            response = self.client.get(url)
        self.assertTemplateUsed(response, "accounts/verify_email_invalid.html")
        user.refresh_from_db()
        self.assertFalse(user.is_email_verified)

    def test_token_cannot_be_reused(self):
        self._register()
        user = User.objects.get(username="newuser")
        url = self._token_url(user)
        self.client.get(url)
        # Re-opening the same link only reports "already verified".
        second = self.client.get(url)
        self.assertTemplateUsed(second, "accounts/verify_email_success.html")
        self.assertTrue(second.context["already_verified"])

    def test_token_for_one_account_cannot_verify_another(self):
        self._register(username="alice", email="alice@example.com")
        self._register(username="bob", email="bob@example.com")
        alice = User.objects.get(username="alice")
        bob = User.objects.get(username="bob")
        bob_uidb64 = urlsafe_base64_encode(force_bytes(bob.pk))
        alice_token = email_verification_token.make_token(alice)
        url = reverse(
            "accounts:verify_email_token",
            kwargs={"uidb64": bob_uidb64, "token": alice_token},
        )
        response = self.client.get(url)
        self.assertTemplateUsed(response, "accounts/verify_email_invalid.html")
        bob.refresh_from_db()
        self.assertFalse(bob.is_email_verified)

    def test_verification_does_not_grant_kyc(self):
        self._register()
        user = User.objects.get(username="newuser")
        self.client.get(self._token_url(user))
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.is_kyc_verified)

    def test_otp_fallback_still_verifies(self):
        self._register()
        user = User.objects.get(username="newuser")
        otp = EmailOTP.objects.filter(user=user, purpose="VERIFY").last()
        response = self.client.post(
            reverse("accounts:verify_email", args=[user.id]), {"code": otp.code}
        )
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )

    # --- login gating -----------------------------------------------------

    def test_login_allowed_after_verification(self):
        self._register()
        user = User.objects.get(username="newuser")
        self.client.get(self._token_url(user))
        self.client.logout()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "newuser", "password": "StrongPass@123"},
        )
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )

    # --- resend / abuse protection ---------------------------------------

    def test_resend_sends_new_email(self):
        self._register()
        mail.outbox.clear()
        response = self.client.post(
            reverse("accounts:resend_verification"),
            {"email": "newuser@example.com"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_is_rate_limited(self):
        self._register()
        mail.outbox.clear()
        self.client.post(
            reverse("accounts:resend_verification"), {"email": "newuser@example.com"}
        )
        # Immediate second attempt is throttled by the cooldown.
        second = self.client.post(
            reverse("accounts:resend_verification"),
            {"email": "newuser@example.com"},
            follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        messages = [str(m) for m in second.context["messages"]]
        self.assertTrue(any("wait" in m.lower() for m in messages))

    def test_resend_does_not_leak_account_existence(self):
        response = self.client.post(
            reverse("accounts:resend_verification"),
            {"email": "nobody@example.com"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("If an account exists" in m for m in messages))

    def test_resend_skips_already_verified_accounts(self):
        User.objects.create_user(
            username="done", email="done@example.com",
            password="Pass@12345", is_email_verified=True,
        )
        self.client.post(
            reverse("accounts:resend_verification"), {"email": "done@example.com"}
        )
        self.assertEqual(len(mail.outbox), 0)


class RoleRestrictionTests(TestCase):
    def setUp(self):
        cache.clear()

    def _verified_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Pass@12345",
            role=role,
            is_email_verified=True,
        )

    def test_seller_can_log_in(self):
        self._verified_user("sell", User.Role.SELLER)
        response = self.client.post(
            reverse("accounts:login"), {"username": "sell", "password": "Pass@12345"}
        )
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )

    def test_bidder_can_log_in(self):
        self._verified_user("bid", User.Role.BIDDER)
        response = self.client.post(
            reverse("accounts:login"), {"username": "bid", "password": "Pass@12345"}
        )
        self.assertRedirects(
            response, reverse("core:dashboard_redirect"), fetch_redirect_response=False
        )

    def test_unverified_seller_cannot_use_seller_features(self):
        seller = User.objects.create_user(
            username="s2", email="s2@example.com", password="Pass@12345",
            role=User.Role.SELLER, is_email_verified=False,
        )
        # Not logged in, so the seller-only page redirects to login.
        response = self.client.get(reverse("products:my_products"))
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_role_user_requires_verification_unless_staff(self):
        admin_role = User.objects.create_user(
            username="boss", email="boss@example.com", password="Pass@12345",
            role=User.Role.ADMIN, is_email_verified=False,
        )
        response = self.client.post(
            reverse("accounts:login"), {"username": "boss", "password": "Pass@12345"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resetuser",
            email="resetuser@example.com",
            password="OldPass@12345",
            role=User.Role.BIDDER,
        )

    def test_reset_form_renders(self):
        response = self.client.get(reverse("accounts:password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_reset.html")

    def test_full_password_reset_workflow(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": self.user.email}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))

        # The email is rendered (this is where the original NoReverseMatch hit).
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        match = re.search(r"/accounts/password/reset/confirm/[^\s]+", body)
        self.assertIsNotNone(match, msg=body)
        confirm_url = match.group(0)

        # Opening the emailed link redirects to the token-free set-password URL.
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 302)
        set_password_url = response.url
        self.assertIn("set-password", set_password_url)

        response = self.client.get(set_password_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_reset_confirm.html")
        self.assertTrue(response.context["validlink"])

        response = self.client.post(
            set_password_url,
            {"new_password1": "BrandNew@9876", "new_password2": "BrandNew@9876"},
        )
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNew@9876"))

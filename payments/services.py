"""
Admin payment-verification helpers.

A payment is only marked VERIFIED by an explicit administrator action — never
because a reference was submitted. Each transition is guarded so a payment can
only move out of PENDING once (no duplicate processing). Verifying a payment
also flips ``Winner.is_payment_verified`` (the application's existing flag for
"payment confirmed").
"""
from django.db import transaction
from django.utils import timezone

from notifications.broadcast import notify

from .models import Payment


class PaymentError(Exception):
    pass


@transaction.atomic
def verify_payment(payment):
    payment = Payment.objects.select_for_update().select_related("winner__product", "payer").get(pk=payment.pk)
    if payment.status != Payment.Status.PENDING:
        raise PaymentError("Only pending payments can be verified.")

    payment.status = Payment.Status.VERIFIED
    payment.verified_at = timezone.now()
    payment.save(update_fields=["status", "verified_at"])

    winner = payment.winner
    if not winner.is_payment_verified:
        winner.is_payment_verified = True
        winner.save(update_fields=["is_payment_verified"])

    notify(
        payment.payer,
        f'Your payment of {payment.amount} for "{winner.product.title}" was verified.',
        link=winner.product.get_absolute_url(),
    )
    return payment


@transaction.atomic
def reject_payment(payment, reason=""):
    payment = Payment.objects.select_for_update().select_related("winner__product", "payer").get(pk=payment.pk)
    if payment.status != Payment.Status.PENDING:
        raise PaymentError("Only pending payments can be rejected.")

    payment.status = Payment.Status.REJECTED
    payment.verified_at = timezone.now()
    payment.save(update_fields=["status", "verified_at"])

    notify(
        payment.payer,
        f'Your payment of {payment.amount} for "{payment.winner.product.title}" was rejected. '
        f'{reason or "Please contact support or re-submit."}',
        link=payment.winner.product.get_absolute_url(),
    )
    return payment

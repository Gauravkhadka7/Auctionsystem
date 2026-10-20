"""
Admin winner-verification helpers.

The schema has no dedicated "winner verified" flag, so verification maps onto
the existing ``Winner.is_verification_submitted`` (bidder submitted KYC) and
``User.is_kyc_verified`` (admin confirmed the documents). Rejection resets the
submission flag so the winner can re-submit.
"""
from django.db import transaction

from notifications.broadcast import notify

from .models import Winner


class VerificationError(Exception):
    pass


@transaction.atomic
def verify_winner(winner):
    winner = Winner.objects.select_for_update().select_related("bidder", "product").get(pk=winner.pk)
    if not winner.is_verification_submitted:
        raise VerificationError("This winner hasn't submitted verification documents yet.")

    bidder = winner.bidder
    if not bidder.is_kyc_verified:
        bidder.is_kyc_verified = True
        bidder.save(update_fields=["is_kyc_verified"])

    notify(
        bidder,
        f'Your identity verification for "{winner.product.title}" was approved. You can now submit payment.',
        link=winner.product.get_absolute_url(),
    )
    return winner


@transaction.atomic
def reject_winner_verification(winner, reason=""):
    winner = Winner.objects.select_for_update().select_related("bidder", "product").get(pk=winner.pk)
    if not winner.is_verification_submitted:
        raise VerificationError("This winner hasn't submitted verification documents yet.")

    winner.is_verification_submitted = False
    winner.save(update_fields=["is_verification_submitted"])

    notify(
        winner.bidder,
        f'Your verification for "{winner.product.title}" needs attention. '
        f'{reason or "Please re-submit your documents."}',
        link=winner.product.get_absolute_url(),
    )
    return winner

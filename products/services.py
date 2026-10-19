"""
Admin listing-moderation helpers.

These deliberately only move a listing along its *documented* lifecycle:
a PENDING listing is approved into UPCOMING (the auction lifecycle engine
promotes it to LIVE when its start time arrives) or rejected. They never
touch prices or declare winners.
"""
from django.db import transaction

from notifications.models import Notification
from .models import Product


class ListingError(Exception):
    pass


@transaction.atomic
def create_product_listing(seller, form, image_formset, spec_formset):
    """Persist a new listing with its gallery images and specifications.

    The product is created in the PENDING state so an administrator can review
    it before the auction is scheduled (PENDING -> UPCOMING -> LIVE -> CLOSED).
    The whole write is atomic: a failure saving an image or specification rolls
    the product back too.
    """
    product = form.save(commit=False)
    product.seller = seller
    product.status = Product.Status.PENDING
    product.current_price = product.starting_price
    product.save()

    image_formset.instance = product
    image_formset.save()

    spec_formset.instance = product
    spec_formset.save()

    return product


@transaction.atomic
def approve_product(product):
    product = Product.objects.select_for_update().get(pk=product.pk)
    if product.status != Product.Status.PENDING:
        raise ListingError("Only listings awaiting approval can be approved.")
    product.status = Product.Status.UPCOMING
    product.admin_remarks = ""
    product.save(update_fields=["status", "admin_remarks"])
    Notification.objects.create(
        user=product.seller,
        message=f'Your listing "{product.title}" was approved and is scheduled to go live.',
        link=product.get_absolute_url(),
    )
    return product


@transaction.atomic
def reject_product(product, reason=""):
    product = Product.objects.select_for_update().get(pk=product.pk)
    if product.status != Product.Status.PENDING:
        raise ListingError("Only listings awaiting approval can be rejected.")
    product.status = Product.Status.REJECTED
    product.admin_remarks = reason or "Rejected by an administrator."
    product.save(update_fields=["status", "admin_remarks"])
    Notification.objects.create(
        user=product.seller,
        message=f'Your listing "{product.title}" was rejected. {product.admin_remarks}',
        link=product.get_absolute_url(),
    )
    return product


@transaction.atomic
def set_featured(product, featured):
    product = Product.objects.select_for_update().get(pk=product.pk)
    if product.status != Product.Status.LIVE:
        raise ListingError("Only live auctions can be featured.")
    product.is_featured = bool(featured)
    product.save(update_fields=["is_featured"])
    return product

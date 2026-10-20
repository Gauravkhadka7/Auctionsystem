from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from .models import Product, ProductImage, ProductSpecification

MAX_IMAGE_SIZE_MB = 5
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def validate_image_upload(image):
    """Validate an uploaded image's content type, size and integrity.

    Django's ``ImageField`` already opens the file with Pillow, but we make the
    rules explicit here so the same validation can be reused and unit-tested.
    """
    if not image:
        return
    content_type = getattr(image, "content_type", "")
    if content_type and content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("Upload a JPEG, PNG, WEBP or GIF image.")
    if image.size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"Images must be {MAX_IMAGE_SIZE_MB} MB or smaller.")
    try:
        image.seek(0)
        Image.open(image).verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("That file isn't a valid image.") from None
    finally:
        image.seek(0)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "title", "category", "subcategory", "brand", "condition", "description",
            "main_image", "starting_price", "reserve_price", "bid_increment",
            "auction_start", "auction_end", "delivery_info",
        ]
        widgets = {
            "auction_start": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "auction_end": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "description": forms.Textarea(attrs={"rows": 5}),
            "delivery_info": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "main_image": "The cover image shown in listings.",
            "starting_price": "The opening bid for your auction.",
            "reserve_price": "Optional. Bids below this price won't win the auction.",
            "bid_increment": "How much each new bid must exceed the previous one.",
            "auction_start": "When your auction opens (must be in the future).",
            "auction_end": "When your auction closes.",
        }

    def clean_main_image(self):
        image = self.cleaned_data.get("main_image")
        validate_image_upload(image)
        return image

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("auction_start")
        end = cleaned.get("auction_end")
        starting = cleaned.get("starting_price")
        reserve = cleaned.get("reserve_price")
        increment = cleaned.get("bid_increment")

        if start and start <= timezone.now():
            self.add_error("auction_start", "The start time must be in the future.")
        if start and end and end <= start:
            self.add_error("auction_end", "The end time must be after the start time.")
        if reserve is not None and starting is not None and reserve < starting:
            self.add_error(
                "reserve_price", "The reserve price can't be lower than the starting price."
            )
        if increment is not None and increment <= 0:
            self.add_error("bid_increment", "The bid increment must be greater than zero.")
        return cleaned


class BaseProductImageFormSet(forms.BaseInlineFormSet):
    """Inline formset that requires at least one image and validates uploads."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        image_count = 0
        for form in self.forms:
            cleaned = getattr(form, "cleaned_data", None)
            if not cleaned or cleaned.get("DELETE"):
                continue
            uploaded = cleaned.get("image")
            if uploaded:
                validate_image_upload(uploaded)
                image_count += 1
            elif form.instance.pk:
                image_count += 1

        if image_count == 0:
            raise ValidationError("Add at least one image to your listing.")


ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    fields=["image"],
    extra=3,
    can_delete=True,
    formset=BaseProductImageFormSet,
)

ProductSpecificationFormSet = inlineformset_factory(
    Product, ProductSpecification, fields=["name", "value"], extra=3, can_delete=True
)


class CommentForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Add a comment..."}))

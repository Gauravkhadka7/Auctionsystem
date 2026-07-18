from django import forms
from django.forms import inlineformset_factory

from .models import Product, ProductImage, ProductSpecification


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "title", "category", "subcategory", "brand", "condition", "description",
            "main_image", "starting_price", "reserve_price", "bid_increment",
            "auction_start", "auction_end", "delivery_info",
        ]
        widgets = {
            "auction_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "auction_end": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 5}),
            "delivery_info": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("auction_start")
        end = cleaned.get("auction_end")
        if start and end and end <= start:
            raise forms.ValidationError("Auction end time must be after the start time.")
        return cleaned


ProductImageFormSet = inlineformset_factory(
    Product, ProductImage, fields=["image"], extra=3, can_delete=True
)

ProductSpecificationFormSet = inlineformset_factory(
    Product, ProductSpecification, fields=["name", "value"], extra=3, can_delete=True
)


class CommentForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Add a comment..."}))

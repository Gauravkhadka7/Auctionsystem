from django import forms

from products.forms import validate_image_upload

from .models import Category, SubCategory


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "icon", "image", "is_active"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        validate_image_upload(image)
        return image


class SubCategoryForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ["category", "name", "is_active"]

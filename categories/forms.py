from django import forms
from .models import Category, SubCategory


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "icon", "is_active"]


class SubCategoryForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ["category", "name", "is_active"]

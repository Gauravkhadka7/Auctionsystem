from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404

from core.permissions import admin_required
from .forms import CategoryForm, SubCategoryForm
from .models import Category, SubCategory


@admin_required
def category_list(request):
    query = request.GET.get("q", "")
    categories = Category.objects.all()
    if query:
        categories = categories.filter(name__icontains=query)
    paginator = Paginator(categories, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "categories/category_list.html", {"page_obj": page_obj, "query": query})


@admin_required
def category_add(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Category created.")
            return redirect("categories:list")
    else:
        form = CategoryForm()
    return render(request, "categories/category_form.html", {"form": form, "is_edit": False})


@admin_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, "Category updated.")
            return redirect("categories:list")
    else:
        form = CategoryForm(instance=category)
    return render(request, "categories/category_form.html", {"form": form, "is_edit": True})


@admin_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.delete()
    messages.success(request, "Category deleted.")
    return redirect("categories:list")


@admin_required
def subcategory_add(request):
    if request.method == "POST":
        form = SubCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Subcategory created.")
            return redirect("categories:list")
    else:
        form = SubCategoryForm()
    return render(request, "categories/subcategory_form.html", {"form": form, "is_edit": False})


@admin_required
def subcategory_edit(request, pk):
    subcategory = get_object_or_404(SubCategory, pk=pk)
    if request.method == "POST":
        form = SubCategoryForm(request.POST, instance=subcategory)
        if form.is_valid():
            form.save()
            messages.success(request, "Subcategory updated.")
            return redirect("categories:list")
    else:
        form = SubCategoryForm(instance=subcategory)
    return render(request, "categories/subcategory_form.html", {"form": form, "is_edit": True})


@admin_required
def subcategory_delete(request, pk):
    subcategory = get_object_or_404(SubCategory, pk=pk)
    subcategory.delete()
    messages.success(request, "Subcategory deleted.")
    return redirect("categories:list")

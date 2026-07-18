from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from bids.models import Bid
from categories.models import Category
from core.permissions import seller_required
from .forms import ProductForm, ProductImageFormSet, ProductSpecificationFormSet, CommentForm
from .models import Product, Comment


def product_list(request):
    products = Product.objects.filter(
        status__in=[Product.Status.LIVE, Product.Status.UPCOMING]
    ).select_related("category", "seller")

    query = request.GET.get("q")
    category_slug = request.GET.get("category")
    status = request.GET.get("status")
    sort = request.GET.get("sort")

    if query:
        products = products.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_slug:
        products = products.filter(category__slug=category_slug)
    if status in ("LIVE", "UPCOMING"):
        products = products.filter(status=status)

    sort_map = {
        "newest": "-created_at",
        "oldest": "created_at",
        "price_high": "-current_price",
        "price_low": "current_price",
        "ending_soon": "auction_end",
    }
    products = products.order_by(sort_map.get(sort, "-created_at"))

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "products/product_list.html", {
        "page_obj": page_obj,
        "categories": Category.objects.filter(is_active=True),
        "query": query or "",
    })


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "subcategory", "seller"), slug=slug
    )
    bid_history = product.bids.select_related("bidder").order_by("-amount")[:20]
    comments = product.comments.select_related("user")
    comment_form = CommentForm()

    user_bid_count = 0
    if request.user.is_authenticated:
        user_bid_count = product.bids.filter(bidder=request.user).count()

    return render(request, "products/product_detail.html", {
        "product": product,
        "bid_history": bid_history,
        "comments": comments,
        "comment_form": comment_form,
        "user_bid_count": user_bid_count,
    })


@login_required
def add_comment(request, slug):
    product = get_object_or_404(Product, slug=slug)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            Comment.objects.create(product=product, user=request.user, text=form.cleaned_data["text"])
            messages.success(request, "Comment posted.")
    return redirect("products:detail", slug=slug)


@seller_required
def my_products(request):
    products = Product.objects.filter(seller=request.user).select_related("category")
    return render(request, "products/my_products.html", {"products": products})


@seller_required
def add_product(request):
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.seller = request.user
            product.status = Product.Status.PENDING
            product.save()

            image_formset = ProductImageFormSet(request.POST, request.FILES, instance=product)
            spec_formset = ProductSpecificationFormSet(request.POST, instance=product)
            if image_formset.is_valid():
                image_formset.save()
            if spec_formset.is_valid():
                spec_formset.save()

            messages.success(request, "Product submitted for admin approval.")
            return redirect("products:my_products")
    else:
        form = ProductForm()
        image_formset = ProductImageFormSet()
        spec_formset = ProductSpecificationFormSet()
        return render(request, "products/product_form.html", {
            "form": form, "image_formset": image_formset, "spec_formset": spec_formset,
            "is_edit": False,
        })

    return render(request, "products/product_form.html", {
        "form": form, "image_formset": ProductImageFormSet(instance=product),
        "spec_formset": ProductSpecificationFormSet(instance=product), "is_edit": False,
    })


@seller_required
def edit_product(request, slug):
    product = get_object_or_404(Product, slug=slug, seller=request.user)
    if product.status == Product.Status.LIVE:
        messages.error(request, "A live auction can't be edited.")
        return redirect("products:my_products")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        image_formset = ProductImageFormSet(request.POST, request.FILES, instance=product)
        spec_formset = ProductSpecificationFormSet(request.POST, instance=product)
        if form.is_valid() and image_formset.is_valid() and spec_formset.is_valid():
            form.save()
            image_formset.save()
            spec_formset.save()
            messages.success(request, "Product updated.")
            return redirect("products:my_products")
    else:
        form = ProductForm(instance=product)
        image_formset = ProductImageFormSet(instance=product)
        spec_formset = ProductSpecificationFormSet(instance=product)

    return render(request, "products/product_form.html", {
        "form": form, "image_formset": image_formset, "spec_formset": spec_formset,
        "is_edit": True, "product": product,
    })


@seller_required
def delete_product(request, slug):
    product = get_object_or_404(Product, slug=slug, seller=request.user)
    if product.status in (Product.Status.LIVE, Product.Status.CLOSED):
        messages.error(request, "Live or closed auctions can't be deleted.")
    else:
        product.delete()
        messages.success(request, "Product deleted.")
    return redirect("products:my_products")

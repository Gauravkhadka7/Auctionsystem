from django.contrib import admin
from .models import Product, ProductImage, ProductSpecification, Comment


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductSpecificationInline(admin.TabularInline):
    model = ProductSpecification
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "category", "status", "current_price", "auction_start", "auction_end", "is_featured")
    list_filter = ("status", "category", "is_featured", "condition")
    search_fields = ("title", "seller__username", "seller__email")
    inlines = [ProductImageInline, ProductSpecificationInline]
    actions = ["approve_products", "reject_products", "feature_products", "suspend_products"]
    readonly_fields = ("current_price", "created_at", "updated_at")

    @admin.action(description="Approve selected products (move Pending → Upcoming)")
    def approve_products(self, request, queryset):
        updated = queryset.filter(status=Product.Status.PENDING).update(status=Product.Status.UPCOMING)
        self.message_user(request, f"{updated} product(s) approved.")

    @admin.action(description="Reject selected products")
    def reject_products(self, request, queryset):
        updated = queryset.update(status=Product.Status.REJECTED)
        self.message_user(request, f"{updated} product(s) rejected.")

    @admin.action(description="Feature selected products")
    def feature_products(self, request, queryset):
        queryset.update(is_featured=True)

    @admin.action(description="Suspend selected products")
    def suspend_products(self, request, queryset):
        queryset.update(status=Product.Status.SUSPENDED)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "created_at")
    search_fields = ("text",)

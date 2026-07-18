from django.contrib import admin
from .models import Winner


@admin.register(Winner)
class WinnerAdmin(admin.ModelAdmin):
    list_display = ("product", "bidder", "winning_price", "is_payment_verified", "is_delivered", "created_at")
    list_filter = ("is_payment_verified", "is_delivered")
    search_fields = ("product__title", "bidder__username")

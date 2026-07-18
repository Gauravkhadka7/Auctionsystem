from django.contrib import admin
from .models import Bid


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("product", "bidder", "amount", "created_at")
    list_filter = ("product__status",)
    search_fields = ("product__title", "bidder__username")

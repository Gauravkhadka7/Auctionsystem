from django.contrib import admin
from .models import SiteContact, NewsletterSubscriber


@admin.register(SiteContact)
class SiteContactAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subject", "is_resolved", "created_at")
    list_filter = ("is_resolved",)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "subscribed_at")

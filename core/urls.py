from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard_redirect, name="dashboard_redirect"),
    path("dashboard/bidder/", views.bidder_dashboard, name="bidder_dashboard"),
    path("dashboard/seller/", views.seller_dashboard, name="seller_dashboard"),
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("about/", views.about, name="about"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("contact/", views.contact, name="contact"),
    path("newsletter/", views.newsletter_signup, name="newsletter_signup"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
]

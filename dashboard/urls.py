from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("search/", views.global_search, name="search"),

    # User management
    path("users/", views.user_list, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("users/<int:pk>/set-role/", views.user_set_role, name="user_set_role"),
    path("users/<int:pk>/toggle-kyc/", views.user_toggle_kyc, name="user_toggle_kyc"),
    path("sellers/", views.seller_list, name="sellers"),
    path("bidders/", views.bidder_list, name="bidders"),

    # Product / listing management
    path("products/", views.product_list, name="products"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/approve/", views.product_approve, name="product_approve"),
    path("products/<int:pk>/reject/", views.product_reject, name="product_reject"),
    path("products/<int:pk>/toggle-featured/", views.product_toggle_featured, name="product_toggle_featured"),

    # Auction lifecycle
    path("auctions/", views.auction_list, name="auctions"),
    path("auctions/sync/", views.auction_sync, name="auction_sync"),

    # Bid history
    path("bids/", views.bid_list, name="bids"),

    # Winner verification
    path("winners/", views.winner_list, name="winners"),
    path("winners/<int:pk>/", views.winner_detail, name="winner_detail"),
    path("winners/<int:pk>/verify/", views.winner_verify, name="winner_verify"),
    path("winners/<int:pk>/reject/", views.winner_reject, name="winner_reject"),

    # Payment verification
    path("payments/", views.payment_list, name="payments"),
    path("payments/<int:pk>/", views.payment_detail, name="payment_detail"),
    path("payments/<int:pk>/verify/", views.payment_verify, name="payment_verify"),
    path("payments/<int:pk>/reject/", views.payment_reject, name="payment_reject"),

    # Reports & activity
    path("reports/", views.reports, name="reports"),
    path("activity/", views.activity, name="activity"),
]

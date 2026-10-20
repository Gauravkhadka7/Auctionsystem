from django.urls import path

from . import views

app_name = "bids"

urlpatterns = [
    path("<slug:slug>/place/", views.place_bid_view, name="place"),
    path("<slug:slug>/place/ajax/", views.place_bid_ajax, name="place_ajax"),
    path("<slug:slug>/status/ajax/", views.bid_status_ajax, name="status_ajax"),
]

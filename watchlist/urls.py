from django.urls import path

from . import views

app_name = "watchlist"

urlpatterns = [
    path("", views.my_watchlist, name="my_watchlist"),
    path("toggle/<slug:slug>/", views.toggle_watchlist, name="toggle"),
]

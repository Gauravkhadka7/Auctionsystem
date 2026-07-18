from django.urls import path
from . import views

app_name = "winners"

urlpatterns = [
    path("", views.winners_public_list, name="list"),
    path("mine/", views.my_wins, name="my_wins"),
    path("<int:pk>/", views.winner_detail, name="detail"),
    path("<int:pk>/verify/", views.submit_verification, name="submit_verification"),
]

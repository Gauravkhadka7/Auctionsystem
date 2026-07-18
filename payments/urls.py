from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("<int:winner_id>/pay/", views.submit_payment, name="submit"),
]

from django.urls import path
from . import views

app_name = "products"

urlpatterns = [
    path("", views.product_list, name="list"),
    path("mine/", views.my_products, name="my_products"),
    path("sell/", views.product_create, name="product_create"),
    path("<slug:slug>/", views.product_detail, name="detail"),
    path("<slug:slug>/edit/", views.edit_product, name="edit"),
    path("<slug:slug>/delete/", views.delete_product, name="delete"),
    path("<slug:slug>/comment/", views.add_comment, name="add_comment"),
]

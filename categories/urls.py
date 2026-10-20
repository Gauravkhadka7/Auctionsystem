from django.urls import path

from . import views

app_name = "categories"

urlpatterns = [
    path("", views.category_list, name="list"),
    path("add/", views.category_add, name="add"),
    path("<int:pk>/edit/", views.category_edit, name="edit"),
    path("<int:pk>/delete/", views.category_delete, name="delete"),
    path("subcategory/add/", views.subcategory_add, name="subcategory_add"),
    path("subcategory/<int:pk>/edit/", views.subcategory_edit, name="subcategory_edit"),
    path("subcategory/<int:pk>/delete/", views.subcategory_delete, name="subcategory_delete"),
]

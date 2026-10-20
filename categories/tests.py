import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .forms import CategoryForm, SubCategoryForm
from .models import Category, SubCategory

User = get_user_model()


def make_image(name="cat.png", color="green"):
    buffer = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class CategoryModelTests(TestCase):
    def test_slug_is_generated_from_name(self):
        category = Category.objects.create(name="Vintage Watches")
        self.assertEqual(category.slug, "vintage-watches")

    def test_image_is_optional_by_default(self):
        category = Category.objects.create(name="Plain")
        self.assertEqual(category.image.name, "")

    def test_str(self):
        category = Category.objects.create(name="Art")
        self.assertEqual(str(category), "Art")

    def test_subcategory_slug_generated(self):
        category = Category.objects.create(name="Art")
        sub = SubCategory.objects.create(category=category, name="Paintings")
        self.assertEqual(sub.slug, "paintings")
        self.assertEqual(str(sub), "Art / Paintings")


class CategoryFormTests(TestCase):
    def test_valid_form_without_image(self):
        form = CategoryForm(data={"name": "Books", "description": "", "icon": "bi-book", "is_active": True})
        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.image.name, "")

    def test_valid_form_with_image_persists_upload(self):
        form = CategoryForm(
            data={"name": "Art", "description": "d", "icon": "", "is_active": True},
            files={"image": make_image()},
        )
        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertTrue(category.image.name.startswith("categories/"))

    def test_non_image_file_is_rejected(self):
        bad = SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")
        form = CategoryForm(
            data={"name": "Bad", "description": "", "icon": "", "is_active": True},
            files={"image": bad},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_oversized_image_is_rejected(self):
        with patch("products.forms.MAX_IMAGE_SIZE_MB", 0):
            form = CategoryForm(
                data={"name": "Big", "description": "", "icon": "", "is_active": True},
                files={"image": make_image()},
            )
            self.assertFalse(form.is_valid())
            self.assertIn("image", form.errors)

    def test_duplicate_name_is_rejected(self):
        Category.objects.create(name="Toys")
        form = CategoryForm(data={"name": "Toys", "description": "", "icon": "", "is_active": True})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_subcategory_form_scoped_to_existing_category(self):
        category = Category.objects.create(name="Art")
        form = SubCategoryForm(data={"category": category.pk, "name": "Sculptures", "is_active": True})
        self.assertTrue(form.is_valid(), form.errors)


class CategoryViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "cat_admin", password="pw12345!", role=User.Role.ADMIN
        )
        self.seller = User.objects.create_user(
            "cat_seller", password="pw12345!", role=User.Role.SELLER
        )
        self.category = Category.objects.create(name="Cameras")
        self.category.image.save("cameras.png", make_image("cameras.png"))
        self.list_url = reverse("categories:list")

    def test_list_requires_admin(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard_redirect"))

    def test_list_requires_login(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_list_renders_thumbnail_and_image_column(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>Image</th>", html=False)
        self.assertContains(response, f'src="{self.category.image.url}"')
        self.assertContains(response, 'alt="Cameras"', html=False)

    def test_list_shows_placeholder_when_image_missing(self):
        Category.objects.create(name="NoPic")
        self.client.force_login(self.admin)
        response = self.client.get(self.list_url)
        self.assertContains(response, "No image")

    def test_admin_can_create_category_with_image(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("categories:add"),
            {
                "name": "Guitars",
                "description": "Axes",
                "icon": "bi-music-note",
                "is_active": "on",
                "image": make_image("guitars.png"),
            },
        )
        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(name="Guitars")
        self.assertTrue(category.image.name.startswith("categories/"))

    def test_create_without_image_is_allowed(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("categories:add"),
            {"name": "Bikes", "description": "", "icon": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(name="Bikes")
        self.assertEqual(category.image.name, "")

    def test_admin_can_edit_category_image(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("categories:edit", args=[self.category.pk]),
            {
                "name": "Cameras",
                "description": "updated",
                "icon": "bi-camera",
                "is_active": "on",
                "image": make_image("replaced.png", color="red"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.category.refresh_from_db()
        self.assertEqual(self.category.description, "updated")
        self.assertNotEqual(self.category.image.name, "categories/cameras.png")

    def test_admin_can_delete_category(self):
        self.client.force_login(self.admin)
        response = self.client.delete(reverse("categories:delete", args=[self.category.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Category.objects.filter(pk=self.category.pk).exists())


class CategoryImageryRenderingTests(TestCase):
    """The theme's category imagery shows up on the public pages."""

    def setUp(self):
        self.category = Category.objects.create(name="Pottery")
        self.category.image.save("pottery.png", make_image("pottery.png"))

    def test_home_page_renders_category_image_card(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "category-card")
        self.assertContains(response, f'src="{self.category.image.url}"')
        self.assertContains(response, 'alt="Pottery"', html=False)

    def test_home_page_falls_back_to_icon_without_image(self):
        Category.objects.create(name="Icon Only", icon="bi-star")
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Icon Only")
        self.assertContains(response, "bi-star")

    def test_product_list_renders_category_chip_with_thumbnail(self):
        response = self.client.get(reverse("products:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "category-chip")
        self.assertContains(response, f'src="{self.category.image.url}"')

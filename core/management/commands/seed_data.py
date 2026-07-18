import random
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User, Profile
from categories.models import Category, SubCategory
from products.models import Product, ProductSpecification
from bids.models import Bid


# 1x1 transparent PNG, used as a lightweight placeholder image so ImageField
# validation passes without needing real product photography.
PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415478da6360000002000155bce6960000000049454e44ae426082"
)


class Command(BaseCommand):
    help = "Seeds the database with demo categories, users, and auction listings."

    def handle(self, *args, **options):
        self.stdout.write("Seeding categories...")
        categories_data = {
            "Electronics": ["Laptops", "Smartphones", "Cameras"],
            "Watches & Jewelry": ["Wristwatches", "Rings"],
            "Art & Collectibles": ["Paintings", "Sculptures", "Coins"],
            "Vehicles": ["Motorbikes", "Bicycles"],
        }
        categories = {}
        for name, subs in categories_data.items():
            cat, _ = Category.objects.get_or_create(name=name)
            categories[name] = cat
            for sub in subs:
                SubCategory.objects.get_or_create(category=cat, name=sub)

        self.stdout.write("Seeding users...")
        admin, created = User.objects.get_or_create(
            username="admin", defaults={"email": "admin@lothouse.local", "role": User.Role.ADMIN}
        )
        if created:
            admin.set_password("Admin@12345")
            admin.is_staff = True
            admin.is_superuser = True
            admin.is_email_verified = True
            admin.save()

        seller, created = User.objects.get_or_create(
            username="demo_seller",
            defaults={"email": "seller@lothouse.local", "role": User.Role.SELLER, "first_name": "Sanjay"},
        )
        if created:
            seller.set_password("Seller@12345")
            seller.is_email_verified = True
            seller.save()
            Profile.objects.get_or_create(user=seller)

        bidders = []
        for i in range(1, 4):
            bidder, created = User.objects.get_or_create(
                username=f"demo_bidder{i}",
                defaults={"email": f"bidder{i}@lothouse.local", "role": User.Role.BIDDER, "first_name": f"Bidder{i}"},
            )
            if created:
                bidder.set_password("Bidder@12345")
                bidder.is_email_verified = True
                bidder.save()
                Profile.objects.get_or_create(user=bidder)
            bidders.append(bidder)

        self.stdout.write("Seeding products...")
        now = timezone.now()
        sample_items = [
            ("Vintage Leica M3 Camera", "Electronics", "Cameras", 15000, 500),
            ("MacBook Pro 14\" M3", "Electronics", "Laptops", 120000, 2000),
            ("Rolex Submariner (Pre-owned)", "Watches & Jewelry", "Wristwatches", 450000, 5000),
            ("Original Oil Landscape Painting", "Art & Collectibles", "Paintings", 8000, 300),
            ("Royal Enfield Classic 350", "Vehicles", "Motorbikes", 180000, 3000),
            ("1947 Commemorative Coin Set", "Art & Collectibles", "Coins", 3000, 100),
        ]

        statuses_cycle = [Product.Status.LIVE, Product.Status.LIVE, Product.Status.UPCOMING, Product.Status.CLOSED]

        for idx, (title, cat_name, sub_name, price, increment) in enumerate(sample_items):
            if Product.objects.filter(title=title).exists():
                continue
            category = categories[cat_name]
            subcategory = category.subcategories.filter(name=sub_name).first()
            status = statuses_cycle[idx % len(statuses_cycle)]

            if status == Product.Status.LIVE:
                start = now - timedelta(hours=2)
                end = now + timedelta(hours=random.randint(2, 48))
            elif status == Product.Status.UPCOMING:
                start = now + timedelta(days=random.randint(1, 5))
                end = start + timedelta(days=3)
            else:
                start = now - timedelta(days=5)
                end = now - timedelta(hours=random.randint(1, 48))

            product = Product(
                seller=seller,
                category=category,
                subcategory=subcategory,
                title=title,
                brand="",
                condition=Product.Condition.USED,
                description=f"A carefully catalogued lot: {title}. Demo listing seeded for local development.",
                starting_price=price,
                bid_increment=increment,
                auction_start=start,
                auction_end=end,
                status=status,
                delivery_info="Buyer arranges pickup or courier within 7 days of payment confirmation.",
            )
            product.main_image.save(f"placeholder_{idx}.png", ContentFile(PLACEHOLDER_PNG), save=False)
            product.save()

            ProductSpecification.objects.create(product=product, name="Condition", value=product.get_condition_display())

            if status in (Product.Status.LIVE, Product.Status.CLOSED):
                current = price
                for b in range(random.randint(2, 5)):
                    bidder = random.choice(bidders)
                    current += increment * random.randint(1, 3)
                    Bid.objects.create(product=product, bidder=bidder, amount=current)
                product.current_price = current
                product.save(update_fields=["current_price"])

        self.stdout.write(self.style.SUCCESS(
            "Seed complete. Login as admin/Admin@12345, demo_seller/Seller@12345, or demo_bidder1/Bidder@12345."
        ))

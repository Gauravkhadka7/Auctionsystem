# LotHouse — Online Auction Management System

A full-stack Django auction platform: sellers list items, bidders place live
bids against a countdown, auctions close automatically, and winners go
through a verification + payment flow before delivery.

This is a **working scaffold**, not a finished production system — it covers
the full request/response lifecycle end to end (see "What's included" below)
with clean, extensible models and views so you can keep building on it for a
portfolio piece, coursework, or internship take-home.

## Tech stack

- Python 3.12, Django 6.0
- Bootstrap 5 + vanilla JS (AJAX bidding, live countdown, dynamic formsets)
- SQLite by default, one env var away from PostgreSQL
- django-crispy-forms + crispy-bootstrap5 for form rendering
- Pillow for image uploads

## Quick start

```bash
python -m venv venv
source venv/bin/activate          # venv\Scripts\activate on Windows
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_data        # optional: demo categories/users/listings
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

### Demo accounts (created by `seed_data`)

| Role   | Username      | Password       |
|--------|---------------|----------------|
| Admin  | admin         | Admin@12345    |
| Seller | demo_seller   | Seller@12345   |
| Bidder | demo_bidder1  | Bidder@12345   |
| Bidder | demo_bidder2  | Bidder@12345   |
| Bidder | demo_bidder3  | Bidder@12345   |

The Django admin (`/django-admin/`) is where an admin approves/rejects
listings, verifies payments, and manages users — it's fully wired up rather
than re-built as a custom panel, which is the pragmatic choice for a project
this size (and a completely normal thing to point out in an interview).

### Environment variables

Copy `.env.example` to `.env` and adjust as needed, then export the values
(or wire up `python-dotenv` / `django-environ` if you want them loaded
automatically — not included by default to keep dependencies minimal).
Sensible defaults exist for everything so the app runs with zero
configuration in development.

## What's included

**Apps:** `accounts`, `categories`, `products`, `auctions`, `bids`, `winners`,
`payments`, `notifications`, `core`.

- **Custom user model** (`accounts.User`) with `ADMIN` / `SELLER` / `BIDDER`
  roles, email OTP verification, and a `Profile` model for KYC/payout details.
- **Product = auction listing.** Each `Product` carries its own auction
  schedule (`auction_start`, `auction_end`), pricing (`starting_price`,
  `reserve_price`, `bid_increment`, `current_price`), and lifecycle `status`
  (`PENDING → UPCOMING → LIVE → CLOSED`, plus `REJECTED` / `SUSPENDED` /
  `CANCELLED`). This is a deliberate simplification vs. a separate `Auction`
  model — one row per listing is easier to reason about and query.
- **Auction lifecycle engine** (`auctions/services.py`): a single
  `sync_auction_states()` function moves products from upcoming → live →
  closed based on server time, creates the `Winner` record, and fires
  notifications. It's invoked two ways:
  - `AuctionLifecycleMiddleware` runs it on every request — zero setup, fine
    for a small/medium site.
  - `python manage.py close_expired_auctions` runs it once — swap to this
    (via cron or Celery beat) and disable the middleware for anything
    higher-traffic.
- **Live bidding**: `bids/services.py` validates and places a bid inside a
  `select_for_update()` transaction to avoid race conditions between two
  simultaneous bidders; `bids/views.py` exposes both a plain-form endpoint
  and a JSON endpoint used by the AJAX widget on the product page
  (`static/js/bidding.js`), which also polls a status endpoint every 5s so
  the price/timer stay fresh for everyone watching.
- **Winner → verification → payment flow**: `winners.Winner` is created
  automatically when an auction closes (if the reserve price was met);
  the winner submits KYC + payout details, then a `payments.Payment` record
  (eSewa / Khalti / bank transfer / cash) that an admin verifies from the
  Django admin.
- **Notifications**: outbid alerts, auction-started/closed alerts, and
  win/payment notices are created as `Notification` rows and surfaced via a
  bell-icon dropdown on every page (`notifications/context_processors.py`).
- **Three "portals"** via role-based dashboards (`core/views.py` +
  `core/permissions.py`'s `@admin_required` / `@seller_required` /
  `@bidder_required` decorators) rather than three separate Django projects —
  simpler to maintain, same effect.
- **Dynamic forms**: sellers add unlimited product images and spec rows via
  Django formsets + a small generic JS helper (`static/js/formset.js`) that
  clones the Django-generated empty form template — no extra JS framework
  needed.

## What's intentionally left as follow-up work

This is a scaffold, and being upfront about the gap is more useful than
pretending it's finished:

- **Search/reporting exports** (PDF/Excel/CSV) — not wired up. Would slot
  into `core` or a new `reports` app using `openpyxl` / `reportlab`.
- **Payment gateway integration** — eSewa/Khalti are modeled as payment
  *methods* with manual admin verification, not live API integrations.
- **Real email delivery** — defaults to the console backend; flip
  `EMAIL_BACKEND` in `.env` to SMTP for real sending.
- **Referral program, careers/partnerships pages** — mentioned in the
  original nav spec but not built; low-value for a portfolio demo.
- **DRF API layer** — the app is server-rendered Django views; a REST layer
  is a natural next step if you want a separate frontend later.
- **Test suite** — none included yet. `pytest-django` + factory_boy would be
  the natural fit given the model structure here.

## Project layout

```
auction_system/     # settings, root urls
accounts/           # custom User, Profile, OTP, auth views
categories/         # Category / SubCategory CRUD (admin-only)
products/           # Product listing CRUD, detail page, comments
auctions/           # lifecycle service + middleware + management command
bids/                # Bid model, placement service, AJAX endpoints
winners/            # Winner model, verification submission
payments/           # Payment model + submission form
notifications/      # Notification model + bell-icon dropdown
core/               # home page, dashboards, static pages, permissions
templates/           # all HTML templates (base.html + per-app folders)
static/              # style.css, countdown.js, bidding.js, formset.js
```

## Switching to PostgreSQL

```bash
pip install psycopg2-binary
# in .env: DB_ENGINE=postgresql, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
python manage.py migrate
```

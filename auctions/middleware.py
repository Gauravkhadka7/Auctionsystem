from .services import sync_auction_states


class AuctionLifecycleMiddleware:
    """
    Lightweight, dependency-free way to keep auction statuses fresh: runs the
    lifecycle sync once per request before the view executes. For higher
    traffic, disable this middleware and instead run
    `python manage.py close_expired_auctions` on a schedule (cron/celery beat).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sync_auction_states()
        return self.get_response(request)

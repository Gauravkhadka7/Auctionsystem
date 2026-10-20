"""WebSocket consumer that streams live auction state to watchers.

Clients connect to /ws/auction/<slug>/ and receive the current state
immediately, then an update every time a bid is placed or the auction's
lifecycle status changes. The HTTP polling endpoints remain as a fallback.
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .broadcast import auction_group_name, serialize_auction


class AuctionConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.group_name = auction_group_name(self.slug)

        if not await self._product_exists():
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(await self._state())

    async def disconnect(self, code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("action") == "status":
            await self.send_json(await self._state())

    async def auction_update(self, event):
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _product_exists(self):
        from products.models import Product

        return Product.objects.filter(slug=self.slug).exists()

    @database_sync_to_async
    def _state(self):
        from products.models import Product

        product = (
            Product.objects.filter(slug=self.slug).select_related("seller").first()
        )
        if product is None:
            return {"type": "auction.update", "slug": self.slug, "status": "CLOSED"}
        return serialize_auction(product, event="snapshot")

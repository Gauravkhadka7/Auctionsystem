"""Per-user notification socket: /ws/notifications/

Sends a snapshot on connect and a ``notification.new`` frame whenever a
Notification row is created for this user (see notifications.broadcast).
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .broadcast import user_group_name


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            await self.close()
            return

        self.group_name = user_group_name(user.pk)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {"type": "notification.snapshot", "unread_count": await self._unread()}
        )

    async def disconnect(self, code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_new(self, event):
        await self.send_json(event)

    @database_sync_to_async
    def _unread(self):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            return 0
        return user.notifications.filter(is_read=False).count()

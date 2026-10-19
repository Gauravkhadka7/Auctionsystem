from django.urls import re_path

from .consumers import AuctionConsumer

websocket_urlpatterns = [
    re_path(r"^ws/auction/(?P<slug>[-\w]+)/$", AuctionConsumer.as_asgi()),
]

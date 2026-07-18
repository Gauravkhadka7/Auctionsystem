def unread_notifications(request):
    """Makes the bell-icon count and dropdown items available on every page."""
    if not request.user.is_authenticated:
        return {}
    qs = request.user.notifications.filter(is_read=False)
    return {
        "unread_notification_count": qs.count(),
        "recent_notifications": request.user.notifications.all()[:6],
    }

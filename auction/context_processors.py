def navigation_context(request):
    """Navigation data shared by every authenticated application page."""
    user = request.user
    if not user.is_authenticated:
        return {'mode': 'BUYER', 'unread_notification_count': 0}

    return {
        'mode': request.session.get('mode', 'BUYER'),
        'unread_notification_count': user.notifications.filter(is_read=False).count(),
    }

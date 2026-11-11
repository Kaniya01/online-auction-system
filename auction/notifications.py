import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import Notification

logger = logging.getLogger(__name__)


def notify_user(user, *, title, message, notification_type, event_key='', link_url=''):
    """Create an idempotent in-app notice and queue a best-effort email."""
    lookup = {'user': user, 'event_key': event_key} if event_key else None
    defaults = {
        'title': title,
        'message': message,
        'notification_type': notification_type,
        'link_url': link_url,
    }
    if lookup:
        notice, created = Notification.objects.get_or_create(**lookup, defaults=defaults)
    else:
        notice = Notification.objects.create(user=user, **defaults)
        created = True

    if created and user.email:
        subject = f'AuctionHub: {title}'
        body = message
        if link_url:
            body += f'\n\nView details: {settings.SITE_BASE_URL.rstrip("/")}{link_url}'

        def deliver():
            try:
                send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
            except Exception:
                # Email delivery must never roll back an auction transaction.
                logger.warning('AuctionHub event email delivery failed (event=%s)', event_key or 'unspecified')

        transaction.on_commit(deliver)
    return notice, created

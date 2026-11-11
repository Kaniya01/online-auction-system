from django.core.management.base import BaseCommand

from auction.browse_views import update_auction_status
from auction.models import Auction


class Command(BaseCommand):
    help = 'Refresh scheduled and active auction statuses and notify winners.'

    def handle(self, *args, **options):
        auctions = Auction.objects.filter(
            status__in=('SCHEDULED', 'ACTIVE')
        ).select_related('product').order_by('pk')

        processed = 0
        changed = 0
        for auction in auctions.iterator():
            before = (
                auction.status,
                auction.current_highest_bid,
                auction.highest_bidder_id,
            )
            update_auction_status(auction)
            after = (
                auction.status,
                auction.current_highest_bid,
                auction.highest_bidder_id,
            )
            processed += 1
            changed += before != after

        self.stdout.write(
            self.style.SUCCESS(
                f'Refreshed {processed} open auction(s); {changed} changed.'
            )
        )

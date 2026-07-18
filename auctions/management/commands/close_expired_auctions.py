from django.core.management.base import BaseCommand

from auctions.services import sync_auction_states


class Command(BaseCommand):
    help = "Activates upcoming auctions whose start time has passed and closes live auctions whose end time has passed."

    def handle(self, *args, **options):
        result = sync_auction_states()
        self.stdout.write(self.style.SUCCESS(
            f"Started {result['started']} auction(s), closed {result['closed']} auction(s)."
        ))

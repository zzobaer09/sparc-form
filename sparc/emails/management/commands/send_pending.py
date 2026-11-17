"""Re-send pending and failed mail jobs (PDF page 3).

Usage:
    python manage.py send_pending                 # from ambassador ID 1
    python manage.py send_pending --from-id 42    # resume after a failure

Requires completed OAuth setup: if this command reports
"Google API needs re-authorisation", open /init/authorise/ as a superuser,
sign in with the sending Gmail, then run this command again.
"""
from time import sleep

from django.core.management.base import BaseCommand

from emails.models import MailJob
from emails.sender import build_service, process_job


class Command(BaseCommand):
    help = ('Re-send pending and failed mail jobs through the Gmail API. '
            'Jobs are processed in ambassador-ID order with a 3 second pause '
            'between sends (Gmail allows roughly 500 recipients per day). '
            'If failures remain, note the printed --from-id and restart from '
            'there. If it reports "re-authorisation", open /init/authorise/ '
            'as a superuser first.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--from-id', type=int, default=1,
            help='Only applications with ambassador ID >= this value are '
                 'processed. Use the ID printed after a failed run to resume.')

    def handle(self, *args, **options):
        from_id = options['from_id']
        jobs = list(MailJob.objects.filter(
            ambassador_id__gte=from_id,
            status__in=[MailJob.PENDING, MailJob.FAILED],
        ).order_by('ambassador_id'))

        if not jobs:
            self.stdout.write('Nothing to send - no pending or failed jobs.')
            return

        try:
            service = build_service()
        except RuntimeError as exc:
            self.stderr.write(
                f'{exc} Open /init/authorise/ as a superuser, sign in with '
                'the sending Gmail, then run this command again.')
            return

        failed = []
        for job in jobs:
            if process_job(job.id, service).status != MailJob.SENT:
                failed.append(job.ambassador_id)
            sleep(3)

        self.stdout.write(f'Done. Sent: {len(jobs) - len(failed)} Failed: {failed}')
        if failed:
            self.stdout.write(
                f'Restart: python manage.py send_pending --from-id {failed[0]}')

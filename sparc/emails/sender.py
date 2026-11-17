"""Gmail sender for the ambassador-received mail (PDF steps 2-3).

Faithful to the PDF's code. The flow:

    process_job_in_thread(job_id)   started after the DB commit
      -> process_job(job_id)       idempotent; writes sent/failed to MailJob
           -> send_mail(...)       builds HTML + plain text, calls Gmail API
                -> build_service() get_credentials() from emails.views
"""
import base64
from email.message import EmailMessage

from django.conf import settings
from django.core.validators import validate_email
from django.db import connection
from django.template.loader import render_to_string
from django.utils import timezone
from googleapiclient.discovery import build

from .models import MailJob
from .views import get_credentials

SUBJECT = 'SPARC 2026 - Ambassador Application Received'


def build_service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError('Google API needs re-authorisation')
    return build(settings.GOOGLE_MAIL_API_NAME,
                 settings.GOOGLE_MAIL_API_VERSION,
                 credentials=creds, cache_discovery=False)


def send_mail(service, to, name):
    validate_email(to)
    ctx = {'name': name,
           'logo_url': f'{settings.SITE_URL}/media_files/SPARC26LogoMin.png'}
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = settings.MAIL_SENDER, to, SUBJECT
    msg.set_content(render_to_string('ambassador_received.txt', ctx))
    msg.add_alternative(render_to_string('ambassador_received.html', ctx),
                        subtype='html')
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return service.users().messages().send(
        userId='me', body={'raw': raw}).execute()['id']


def process_job(job_id, service=None):
    job = MailJob.objects.select_related('ambassador').get(pk=job_id)
    if job.status == MailJob.SENT:
        return job  # never send twice
    a = job.ambassador
    try:
        job.gmail_message_id = send_mail(
            service or build_service(), job.to_email, a.name)
        job.status, job.error, job.sent_at = MailJob.SENT, '', timezone.now()
        print(f'[OK] ID={a.id} Name={a.name} Email={job.to_email} '
              f'MsgId={job.gmail_message_id}', flush=True)
    except Exception as exc:
        job.status, job.error = MailJob.FAILED, str(exc)[:500]
        print(f'[FAIL] ID={a.id} Name={a.name} Reason={job.error}', flush=True)
    job.save()
    return job


def process_job_in_thread(job_id):
    try:
        process_job(job_id)
    finally:
        connection.close()

"""Phase 6 test suite for the emails app.

Everything that touches Google is exercised against fakes (the same
FakeService pattern the Phase 4/5 verifications used) so the suite runs
offline, deterministically and fast:

- sender:    process_job lifecycle, idempotency, error truncation, the exact
             MIME message (subject/from/text+html/logo, no PII), logging
- command:   send_pending --from-id, forced failure + restart hint,
             nothing-to-send, unauthorised run, help text
- OAuth:     byte-exact URLs, staff-only access, state checks, success and
             failure paths with a fake Flow, get_credentials() branches
- admin:     the "Send now" action (send / cannot-send / nothing-to-send)
- settings:  the LOGGING config for the emails logger
"""
import base64
import itertools
import logging
import os
from email import message_from_bytes
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

import emails.admin as emails_admin
import emails.management.commands.send_pending as send_pending_cmd
import emails.views
from emails.models import MailJob
from emails.sender import build_service, process_job, send_mail
from emails.views import get_credentials
from registration.models import Ambassador

SUBJECT = 'SPARC 2026 - Ambassador Application Received'


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

class FakeService:
    """Stands in for the Gmail discovery service; records raw bodies."""

    def __init__(self, error=None):
        self.error = error
        self.bodies = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId=None, body=None):
        self.bodies.append(body)
        if self.error is not None:
            raise self.error

        class Result:
            def execute(self):
                return {'id': 'fake-msg-001'}
        return Result()


_email_seq = itertools.count(1)


def make_ambassador(email=None, name='Mail Tester'):
    # photo as a path string: no file is written to disk in these tests.
    return Ambassador.objects.create(
        name=name, email=email or f'mail-test-{next(_email_seq)}@example.com',
        whatsapp='+8801700000000', date_of_birth='2000-01-01',
        gender='female', university='NSU', department='CSE',
        year_of_study='2nd', student_id='ID-1',
        photo='ambassador_photos/mail-test.jpg', bio='b', why_ambassador='w',
        activities=[], heard_from='friend', agree_info_accurate=True,
        agree_media_usage=True, agree_points_ranking=True,
        agree_contact_consent=True)


def make_job(amb, status=MailJob.PENDING):
    job = MailJob.objects.create(
        campaign='ambassador_received', ambassador=amb, to_email=amb.email)
    if status == MailJob.FAILED:
        job.status, job.error = MailJob.FAILED, 'simulated Gmail outage'
        job.save()
    elif status == MailJob.SENT:
        job.status, job.gmail_message_id = MailJob.SENT, 'already-sent-id'
        job.save()
    return job


def strip_oauth_env():
    """Force get_credentials() to see an unauthorised environment."""
    return mock.patch.dict(os.environ, {
        'GOOGLE_CLOUD_TOKEN': '',
        'GOOGLE_CLOUD_REFRESH_TOKEN': '',
    })


def parse_mail(raw):
    """Decode a base64 'raw' Gmail body and split out its main parts.

    Returns (parsed_message, text_part, html_part, logo_part) with any of
    the three parts possibly None; works for any MIME nesting.
    """
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw))
    text_part = html_part = logo_part = None
    for part in parsed.walk():
        ctype = part.get_content_type()
        if ctype == 'text/plain' and text_part is None:
            text_part = part
        elif ctype == 'text/html' and html_part is None:
            html_part = part
        elif ctype == 'image/png':
            logo_part = part
    return parsed, text_part, html_part, logo_part


class StaffLoginMixin(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser(
            'ops-admin', 'ops-admin@example.com', 'secret-123')
        self.client.force_login(self.user)


# ----------------------------------------------------------------------
# sender
# ----------------------------------------------------------------------

class SenderTests(TestCase):
    def test_process_job_sends_pending_job(self):
        amb = make_ambassador(name='Sender One')
        job = make_job(amb)
        service = FakeService()
        result = process_job(job.id, service)
        self.assertEqual(result.status, MailJob.SENT)
        self.assertEqual(result.gmail_message_id, 'fake-msg-001')
        self.assertEqual(result.error, '')
        self.assertIsNotNone(result.sent_at)
        self.assertEqual(len(service.bodies), 1)

    def test_process_job_never_sends_twice(self):
        amb = make_ambassador(name='Sender Two')
        job = make_job(amb, status=MailJob.SENT)
        service = FakeService()
        result = process_job(job.id, service)
        self.assertEqual(result.status, MailJob.SENT)
        self.assertEqual(result.gmail_message_id, 'already-sent-id')
        self.assertEqual(service.bodies, [])  # no API call at all

    def test_process_job_failure_recorded(self):
        amb = make_ambassador(name='Sender Three')
        job = make_job(amb)
        service = FakeService(error=RuntimeError('simulated Gmail outage'))
        result = process_job(job.id, service)
        self.assertEqual(result.status, MailJob.FAILED)
        self.assertEqual(result.error, 'simulated Gmail outage')
        self.assertEqual(result.gmail_message_id, '')

    def test_process_job_truncates_error_to_500_chars(self):
        amb = make_ambassador(name='Sender Four')
        job = make_job(amb)
        service = FakeService(error=RuntimeError('x' * 1000))
        result = process_job(job.id, service)
        self.assertEqual(len(result.error), 500)

    @override_settings(MAIL_SENDER='Test Sender <test@example.com>',
                       SITE_URL='http://testsite')
    def test_send_mail_builds_exact_mime(self):
        service = FakeService()
        message_id = send_mail(service, 'recipient@example.com', 'Alice')
        self.assertEqual(message_id, 'fake-msg-001')
        self.assertEqual(len(service.bodies), 1)

        raw = service.bodies[0]['raw']
        parsed, text_part, html_part, logo_part = parse_mail(raw)
        self.assertEqual(parsed['Subject'], SUBJECT)
        self.assertEqual(parsed['From'], 'Test Sender <test@example.com>')
        self.assertEqual(parsed['To'], 'recipient@example.com')
        self.assertTrue(parsed.is_multipart())
        text = text_part.get_payload(decode=True).decode()
        html = html_part.get_payload(decode=True).decode()
        self.assertIn('Dear Alice', text)
        self.assertIn('Alice', html)
        # Plain text+html pair; the blue header is a text banner, so the
        # mail carries no image part at all (email-client-safe).
        self.assertEqual(parsed.get_content_type(), 'multipart/alternative')
        self.assertIsNone(logo_part)
        # The header shows the branch name, large and white on the blue bg.
        self.assertIn('IEEE NSU SB', html)
        self.assertIn('color:#ffffff', html)

    @override_settings(MAIL_SENDER='Test Sender <test@example.com>',
                       SITE_URL='http://testsite')
    def test_send_mail_escapes_html_in_name(self):
        service = FakeService()
        malicious_name = '<script>alert("hack")</script>'
        send_mail(service, 'recipient@example.com', malicious_name)
        raw = service.bodies[0]['raw']
        parsed, text_part, html_part, logo_part = parse_mail(raw)
        html = html_part.get_payload(decode=True).decode()
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;alert(&quot;hack&quot;)&lt;/script&gt;', html)

    def test_send_mail_rejects_invalid_recipient(self):
        with self.assertRaises(ValidationError):
            send_mail(FakeService(), 'not-an-email', 'Alice')

    def test_build_service_without_credentials_raises_friendly_error(self):
        emails.views._cached_credentials = None
        self.addCleanup(setattr, emails.views, '_cached_credentials', None)
        with strip_oauth_env():
            with self.assertRaises(RuntimeError) as ctx:
                build_service()
        self.assertIn('re-authorisation', str(ctx.exception))

    def test_ok_and_fail_lines_reach_the_emails_logger(self):
        amb = make_ambassador(name='Log Sender')
        job = make_job(amb)
        with self.assertLogs('emails', level='INFO') as captured:
            process_job(job.id, FakeService())
        self.assertTrue(any('[OK]' in line for line in captured.output))

        amb2 = make_ambassador(name='Log Sender 2')
        job2 = make_job(amb2)
        with self.assertLogs('emails', level='INFO') as captured:
            process_job(job2.id, FakeService(error=RuntimeError('boom')))
        self.assertTrue(any('[FAIL]' in line for line in captured.output))


# ----------------------------------------------------------------------
# send_pending command
# ----------------------------------------------------------------------

class SendPendingCommandTests(TestCase):
    def setUp(self):
        super().setUp()
        # Tests stay fast; build_service is patched per-test.
        self._sleep = mock.patch.object(
            send_pending_cmd, 'sleep', new=lambda seconds: None)
        self._sleep.start()
        self.addCleanup(self._sleep.stop)

    def run_command(self, *args, **kwargs):
        from io import StringIO
        out, err = StringIO(), StringIO()
        call_command('send_pending', *args, stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    def test_help_text_mentions_from_id_and_authorise(self):
        self.assertIn('--from-id', send_pending_cmd.Command.help)
        self.assertIn('authorise', send_pending_cmd.Command.help)

    def test_from_id_skips_lower_ids_and_sends_the_rest(self):
        a = make_ambassador(name='Cmd A')   # pending, lower ID -> skipped
        make_job(a)
        b = make_ambassador(name='Cmd B')   # failed -> retried
        job_b = make_job(b, status=MailJob.FAILED)
        c = make_ambassador(name='Cmd C')   # pending -> sent
        make_job(c)
        s = make_ambassador(name='Cmd S')   # sent -> untouched
        job_s = make_job(s, status=MailJob.SENT)

        service = FakeService()
        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=service):
            out, _ = self.run_command(from_id=b.pk)

        self.assertIn('Done. Sent: 2 Failed: []', out)
        job_b.refresh_from_db()
        self.assertEqual(job_b.status, MailJob.SENT)
        self.assertEqual(
            MailJob.objects.get(ambassador=a).status, MailJob.PENDING)
        self.assertEqual(
            MailJob.objects.get(ambassador=c).status, MailJob.SENT)
        job_s.refresh_from_db()
        self.assertEqual(job_s.gmail_message_id, 'already-sent-id')
        self.assertEqual(len(service.bodies), 2)

    def test_second_run_picks_up_the_skipped_job(self):
        a = make_ambassador(name='Cmd Late')
        make_job(a)
        s = make_ambassador(name='Cmd High')
        make_job(s, status=MailJob.SENT)

        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=FakeService()):
            out, _ = self.run_command(
                from_id=s.pk)   # skips a, s already sent
        self.assertIn('Nothing to send - no pending or failed jobs.', out)
        self.assertEqual(
            MailJob.objects.get(ambassador=a).status, MailJob.PENDING)

        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=FakeService()):
            out, _ = self.run_command()   # default from-id=1 -> a is sent
        self.assertIn('Done. Sent: 1 Failed: []', out)
        self.assertEqual(
            MailJob.objects.get(ambassador=a).status, MailJob.SENT)

    def test_nothing_to_send(self):
        amb = make_ambassador(name='Cmd Done')
        make_job(amb, status=MailJob.SENT)
        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=FakeService()):
            out, _ = self.run_command()
        self.assertIn('Nothing to send - no pending or failed jobs.', out)

    def test_forced_failure_sets_failed_and_prints_restart_hint(self):
        amb = make_ambassador(name='Cmd Fail')
        job = make_job(amb)
        bad = FakeService(error=RuntimeError('simulated Gmail outage'))
        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=bad):
            out, _ = self.run_command()
        self.assertIn('Done. Sent: 0 Failed: [%d]' % amb.id, out)
        self.assertIn(
            'Restart: python manage.py send_pending --from-id %d' % amb.id,
            out)
        job.refresh_from_db()
        self.assertEqual(job.status, MailJob.FAILED)
        self.assertEqual(job.error, 'simulated Gmail outage')

    def test_fix_then_from_id_sends_only_the_failed_job(self):
        amb = make_ambassador(name='Cmd Fixed')
        job = make_job(amb)
        ok = make_ambassador(name='Cmd Already')
        ok_job = make_job(ok, status=MailJob.SENT)

        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=FakeService(
                                   error=RuntimeError('outage'))):
            self.run_command()
        job.refresh_from_db()
        self.assertEqual(job.status, MailJob.FAILED)

        # "Fixing the secret": a working service + resume from the failed ID.
        service = FakeService()
        with mock.patch.object(send_pending_cmd, 'build_service',
                               return_value=service):
            out, _ = self.run_command(from_id=amb.id)
        self.assertIn('Done. Sent: 1 Failed: []', out)
        job.refresh_from_db()
        ok_job.refresh_from_db()
        self.assertEqual(job.status, MailJob.SENT)
        self.assertEqual(ok_job.gmail_message_id, 'already-sent-id')
        self.assertEqual(len(service.bodies), 1)

    def test_unauthorised_run_prints_friendly_stderr(self):
        amb = make_ambassador(name='Cmd NoAuth')
        job = make_job(amb)
        emails.views._cached_credentials = None
        self.addCleanup(setattr, emails.views, '_cached_credentials', None)
        with strip_oauth_env():
            out, err = self.run_command()
        self.assertIn('re-authorisation', err)
        self.assertIn('/init/authorise/', err)
        self.assertEqual(out, '')
        job.refresh_from_db()
        self.assertEqual(job.status, MailJob.PENDING)  # untouched, no crash


# ----------------------------------------------------------------------
# OAuth views
# ----------------------------------------------------------------------

class OAuthViewTests(StaffLoginMixin):
    def test_urls_are_byte_exact_per_pdf(self):
        self.assertEqual(reverse('emails:authorise'), '/init/authorise/')
        # NO trailing slash on the callback - Google compares it literally.
        self.assertEqual(reverse('emails:oauth2callback'), '/init/oauth2callback')

    def test_callback_with_trailing_slash_is_404(self):
        self.assertEqual(
            self.client.get('/init/oauth2callback/').status_code, 404)

    def test_authorise_requires_staff(self):
        self.client.logout()
        response = self.client.get('/init/authorise/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/admin/login'))

    @override_settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='')
    def test_authorise_without_client_credentials_shows_guidance(self):
        self.assertFalse(emails.views._configured())
        response = self.client.get('/init/authorise/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'emails/authorise_result.html')
        self.assertContains(response, 'not set in .env')

    @override_settings(
        GOOGLE_CLIENT_ID='fake-id.apps.googleusercontent.com',
        GOOGLE_CLIENT_SECRET='fake-secret')
    def test_authorise_redirects_to_google_consent(self):
        response = self.client.get('/init/authorise/')
        self.assertEqual(response.status_code, 302)
        url = response['Location']
        self.assertTrue(
            url.startswith('https://accounts.google.com/o/oauth2/auth'))
        self.assertIn('client_id=fake-id', url)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['access_type'], ['offline'])
        self.assertEqual(query['prompt'], ['consent'])
        self.assertIn('oauth_state', self.client.session)
        # The PKCE verifier must be stashed for the callback to restore.
        self.assertTrue(self.client.session.get('oauth_verifier'))

    def test_callback_without_state_is_rejected(self):
        response = self.client.get('/init/oauth2callback')
        self.assertEqual(response.status_code, 400)

    def test_callback_with_wrong_state_is_rejected(self):
        session = self.client.session
        session['oauth_state'] = 'expected'
        session.save()
        response = self.client.get(
            '/init/oauth2callback', {'state': 'forged', 'code': 'x'})
        self.assertEqual(response.status_code, 400)

    def test_callback_reports_google_error(self):
        session = self.client.session
        session['oauth_state'] = 'expected'
        session.save()
        response = self.client.get(
            '/init/oauth2callback',
            {'state': 'expected', 'error': 'access_denied'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Google returned: access_denied')
        self.assertContains(response, 'Test user')

    @override_settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='')
    def test_callback_without_client_credentials_is_friendly(self):
        session = self.client.session
        session['oauth_state'] = 'expected'
        session.save()
        response = self.client.get(
            '/init/oauth2callback', {'state': 'expected', 'code': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Client credentials missing')

    def test_callback_success_persists_tokens(self):
        fake_creds = SimpleNamespace(token='tok-123', refresh_token='rtok-123')
        fake_flow = mock.MagicMock()
        fake_flow.credentials = fake_creds

        with mock.patch.object(emails.views, '_configured', return_value=True), \
             mock.patch.object(emails.views, '_build_flow',
                               return_value=fake_flow), \
             mock.patch.object(emails.views, '_persist_token') as persist:
            session = self.client.session
            session['oauth_state'] = 'expected'
            session['oauth_verifier'] = 'pkce-verifier-123'
            session.save()
            response = self.client.get(
                '/init/oauth2callback',
                {'state': 'expected', 'code': 'auth-code-1'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'now filled in .env')
        fake_flow.fetch_token.assert_called_once_with(code='auth-code-1')
        # The verifier stashed at /init/authorise/ was restored onto the flow.
        self.assertEqual(fake_flow.code_verifier, 'pkce-verifier-123')
        persist.assert_any_call('GOOGLE_CLOUD_TOKEN', 'tok-123')
        persist.assert_any_call('GOOGLE_CLOUD_REFRESH_TOKEN', 'rtok-123')


class GetCredentialsTests(TestCase):
    def setUp(self):
        super().setUp()
        emails.views._cached_credentials = None
        self.addCleanup(setattr, emails.views, '_cached_credentials', None)

    def test_no_refresh_token_returns_none(self):
        with strip_oauth_env():
            self.assertIsNone(get_credentials())

    def test_refresh_failure_returns_none(self):
        class FailingCredentials:
            def __init__(self, **kwargs):
                self.token = kwargs.get('token')
                self.valid = False
                self.expiry = None

            def refresh(self, request):
                raise RuntimeError('RefreshError: invalid_grant')

        env = mock.patch.dict(os.environ, {
            'GOOGLE_CLOUD_TOKEN': 'old-token',
            'GOOGLE_CLOUD_REFRESH_TOKEN': 'rt',
        })
        with env, \
             mock.patch.object(emails.views, 'Credentials',
                               FailingCredentials), \
             mock.patch.object(emails.views, 'Request', object):
            self.assertIsNone(get_credentials())

    def test_refresh_success_persists_new_token_and_is_cached(self):
        class WorkingCredentials:
            def __init__(self, **kwargs):
                self.token = kwargs.get('token')
                self.refresh_token = kwargs.get('refresh_token')
                self.valid = False
                self.expiry = None

            def refresh(self, request):
                self.token = 'new-token'
                self.valid = True
                self.expiry = None

        env = mock.patch.dict(os.environ, {
            'GOOGLE_CLOUD_TOKEN': 'old-token',
            'GOOGLE_CLOUD_REFRESH_TOKEN': 'rt',
        })
        with env, \
             mock.patch.object(emails.views, 'Credentials',
                               WorkingCredentials), \
             mock.patch.object(emails.views, 'Request', object), \
             mock.patch.object(emails.views, '_persist_token') as persist:
            creds = get_credentials()
            self.assertIsInstance(creds, WorkingCredentials)
            self.assertEqual(creds.token, 'new-token')
            persist.assert_called_once_with(
                'GOOGLE_CLOUD_TOKEN', 'new-token')
            # Second call is served from the process cache.
            self.assertIs(get_credentials(), creds)

    def test_cached_valid_credentials_short_circuit(self):
        sentinel = SimpleNamespace(valid=True)
        emails.views._cached_credentials = sentinel
        self.addCleanup(setattr, emails.views, '_cached_credentials', None)
        self.assertIs(get_credentials(), sentinel)


# ----------------------------------------------------------------------
# admin "Send now" action
# ----------------------------------------------------------------------

class AdminActionTests(StaffLoginMixin):
    def post_action(self, job):
        return self.client.post(
            '/admin/emails/mailjob/',
            {'action': 'retry_selected', '_selected_action': [str(job.id)],
             'index': '0', 'select_across': '0'},
            follow=True)

    def admin_messages(self, response):
        # joined into one string so assertIn works on substrings
        return '\n'.join(str(m.message) for m in response.context['messages'])

    def test_send_now_processes_pending_job(self):
        amb = make_ambassador(name='Admin Send')
        job = make_job(amb)
        service = FakeService()
        with mock.patch.object(emails_admin, 'build_service',
                               return_value=service):
            response = self.post_action(job)
        job.refresh_from_db()
        self.assertEqual(job.status, MailJob.SENT)
        self.assertEqual(len(service.bodies), 1)
        self.assertIn('Send now finished: 1 sent, 0 failed.',
                      self.admin_messages(response))

    def test_send_now_without_authorisation_is_friendly(self):
        amb = make_ambassador(name='Admin NoAuth')
        job = make_job(amb)
        with mock.patch.object(emails_admin, 'build_service',
                               side_effect=RuntimeError(
                                   'Google API needs re-authorisation')):
            response = self.post_action(job)
        job.refresh_from_db()
        self.assertEqual(job.status, MailJob.PENDING)
        self.assertIn('Cannot send now', self.admin_messages(response))

    def test_send_now_skips_already_sent_jobs(self):
        amb = make_ambassador(name='Admin Done')
        job = make_job(amb, status=MailJob.SENT)
        service = FakeService()
        with mock.patch.object(emails_admin, 'build_service',
                               return_value=service):
            response = self.post_action(job)
        self.assertEqual(service.bodies, [])
        self.assertIn('Nothing to send - selection contains only '
                      'already-sent jobs.', self.admin_messages(response))


# ----------------------------------------------------------------------
# settings
# ----------------------------------------------------------------------

class LoggingConfigTests(TestCase):
    def test_emails_logger_routes_to_console_at_info(self):
        logger_config = settings.LOGGING['loggers']['emails']
        self.assertIn('console', logger_config['handlers'])
        self.assertEqual(logger_config['level'], 'INFO')
        self.assertFalse(logger_config['propagate'])
        self.assertIn('console', settings.LOGGING['handlers'])

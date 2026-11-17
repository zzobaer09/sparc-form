"""Phase 6 test suite for the registration app.

Covers the PDF verification rows that can be checked locally:

- models: unique email, one row per application, MailJob constraint/cascade
- form:   every PDF validation rule (conditional IEEE, 50-word bio, photo
          type/size, WhatsApp format, agreements, activity whitelist,
          unique email)
- views:  GET renders the form, POST success/duplicate/error flows with the
          exact AJAX JSON contract, /thanks/, mail-job hook after commit
- admin:  both models registered, changelists render
"""
import json
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.contrib import admin as django_admin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from PIL import Image

from emails.models import MailJob

from .forms import AmbassadorForm
from .models import Ambassador


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def jpeg_bytes(size=(40, 40)):
    buf = BytesIO()
    Image.new('RGB', size, (10, 10, 10)).save(buf, 'JPEG')
    return buf.getvalue()


def png_bytes():
    buf = BytesIO()
    Image.new('RGB', (30, 30), (1, 2, 3)).save(buf, 'PNG')
    return buf.getvalue()


def oversized_png_bytes():
    """A valid PNG padded past the 10 MB limit (trailing bytes are ignored
    by decoders, so the file is still a real image for ImageField)."""
    return png_bytes() + b'\x00' * (10 * 1024 * 1024)


def photo_file(name='photo.jpg', data=None):
    return SimpleUploadedFile(
        name, data if data is not None else jpeg_bytes(), content_type='image/jpeg')


def valid_data(**overrides):
    """Complete, valid form data. The photo travels separately in files.

    Overrides replace entries; an override of None removes the key, which
    is how tests simulate an unchecked/missing field.
    """
    payload = {
        'name': 'Test Applicant',
        'email': 'applicant@example.com',
        'whatsapp': '+8801712345678',
        'date_of_birth': '2000-01-01',
        'gender': 'female',
        'university': 'North South University',
        'department': 'CSE',
        'year_of_study': '2nd',
        'student_id': 'NSU-203',
        'is_ieee_member': 'False',
        'ieee_number': '', 'ieee_grade': '', 'ieee_branch': '', 'ieee_position': '',
        'bio': 'A short bio with a few words only.',
        'why_ambassador': 'I love SPARC.',
        'activities': ['social_media_posts'],
        'heard_from': 'friend',
        'agree_info_accurate': 'on',
        'agree_media_usage': 'on',
        'agree_points_ranking': 'on',
        'agree_contact_consent': 'on',
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def valid_files(**overrides):
    """Upload files for a valid POST; photo=None produces an empty dict."""
    overrides.setdefault('photo', photo_file())
    return {key: value for key, value in overrides.items() if value is not None}


def full_post_payload(**overrides):
    """One dict with data + files, ready for the Django test client."""
    payload = valid_data(**overrides)
    payload.update(valid_files())
    return payload


class MediaRootMixin:
    """Point MEDIA_ROOT at a fresh temp dir; remove it afterwards."""

    def setUp(self):
        super().setUp()
        self._media_root = tempfile.mkdtemp(prefix='sparc-test-media-')
        override = override_settings(MEDIA_ROOT=self._media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, True)


def make_ambassador(email='db@example.com', photo='ambassador_photos/db.jpg'):
    """Model-level row; photo is a path string so no file is written."""
    return Ambassador.objects.create(
        name='DB Applicant', email=email, whatsapp='+8801700000000',
        date_of_birth='2000-01-01', gender='female', university='NSU',
        department='CSE', year_of_study='2nd', student_id='ID-1',
        photo=photo, bio='b', why_ambassador='w', activities=[],
        heard_from='friend', agree_info_accurate=True, agree_media_usage=True,
        agree_points_ranking=True, agree_contact_consent=True)


# ----------------------------------------------------------------------
# models
# ----------------------------------------------------------------------

class ModelTests(TestCase):
    def test_str_and_mailjob_defaults(self):
        amb = make_ambassador()
        job = MailJob.objects.create(
            campaign='ambassador_received', ambassador=amb, to_email=amb.email)
        self.assertEqual(str(amb), 'DB Applicant <db@example.com>')
        self.assertEqual(
            str(job), 'ambassador_received -> db@example.com (pending)')
        self.assertEqual(job.status, MailJob.PENDING)
        self.assertEqual(job.error, '')
        self.assertIsNone(job.sent_at)
        self.assertEqual(job.gmail_message_id, '')

    def test_unique_email_constraint(self):
        make_ambassador(email='dupe@example.com')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_ambassador(email='dupe@example.com')

    def test_one_mail_per_campaign_constraint(self):
        amb = make_ambassador()
        MailJob.objects.create(
            campaign='ambassador_received', ambassador=amb, to_email=amb.email)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MailJob.objects.create(
                    campaign='ambassador_received', ambassador=amb,
                    to_email=amb.email)
        # A different campaign for the same ambassador is allowed.
        MailJob.objects.create(
            campaign='other_campaign', ambassador=amb, to_email=amb.email)

    def test_deleting_ambassador_cascades_to_mailjob(self):
        amb = make_ambassador()
        job = MailJob.objects.create(
            campaign='ambassador_received', ambassador=amb, to_email=amb.email)
        amb.delete()
        self.assertFalse(MailJob.objects.filter(pk=job.pk).exists())


# ----------------------------------------------------------------------
# form validation (every PDF rule)
# ----------------------------------------------------------------------

class FormTests(TestCase):
    def form(self, **overrides):
        """Build AmbassadorForm from a valid payload with overrides.

        A file-like override replaces the photo; a None override removes
        the key from both data and files (simulating a missing field);
        anything else is a plain data override.
        """
        data, files = valid_data(), valid_files()
        for key, value in overrides.items():
            if hasattr(value, 'read'):
                files[key] = value
            elif value is None:
                data.pop(key, None)
                files.pop(key, None)
            else:
                data[key] = value
        return AmbassadorForm(data, files)

    def test_valid_form_and_cleaning(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'applicant@example.com')
        self.assertIs(form.cleaned_data['is_ieee_member'], False)
        self.assertEqual(form.cleaned_data['activities'], ['social_media_posts'])

    def test_email_is_lowercased_and_duplicate_is_case_insensitive(self):
        make_ambassador(email='taken@example.com')
        # Different address: fine, stored lower-case.
        form = self.form(email='UPPER@EXAMPLE.com')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'upper@example.com')
        # Same address with different casing: rejected.
        form = self.form(email='TAKEN@EXAMPLE.com')
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_bio_word_limit(self):
        form = self.form(bio='word ' * 50)
        self.assertTrue(form.is_valid(), form.errors)
        form = self.form(bio='word ' * 51)
        self.assertFalse(form.is_valid())
        self.assertIn('bio', form.errors)
        self.assertIn('50', form.errors['bio'][0])

    def test_whatsapp_formats(self):
        for number in ('+8801712345678', '0171234567', '017 123-45(6)'):
            form = self.form(whatsapp=number)
            self.assertTrue(form.is_valid(), form.errors)
        for number in ('abc123', '12', 'not a phone'):
            form = self.form(whatsapp=number)
            self.assertFalse(form.is_valid())
            self.assertIn('whatsapp', form.errors)

    def test_photo_required(self):
        form = self.form(photo=None)
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_photo_accepts_png(self):
        form = self.form(photo=photo_file('photo.png', png_bytes()))
        self.assertTrue(form.is_valid(), form.errors)

    def test_photo_rejects_wrong_extension(self):
        form = self.form(photo=photo_file('photo.gif', jpeg_bytes()))
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_photo_rejects_corrupted_file(self):
        form = self.form(photo=photo_file('fake.jpg', b'this is not an image'))
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_photo_rejects_oversized(self):
        form = self.form(photo=photo_file('big.png', oversized_png_bytes()))
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)
        self.assertIn('Maximum is 10 MB', form.errors['photo'][0])

    def test_ieee_fields_required_only_for_members(self):
        # Yes + missing IEEE data -> four errors.
        form = self.form(is_ieee_member='True')
        self.assertFalse(form.is_valid())
        for field in ('ieee_number', 'ieee_grade', 'ieee_branch',
                      'ieee_position'):
            self.assertIn(field, form.errors)
        # Yes + complete IEEE data -> fine.
        form = self.form(is_ieee_member='True', ieee_number='IEEE-123',
                         ieee_grade='student_member', ieee_branch='IEEE NSU SB',
                         ieee_position='Member')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data['is_ieee_member'], True)
        # No + empty IEEE data -> fine.
        form = self.form(is_ieee_member='False')
        self.assertTrue(form.is_valid(), form.errors)

    def test_all_four_agreements_required(self):
        for field in ('agree_info_accurate', 'agree_media_usage',
                      'agree_points_ranking', 'agree_contact_consent'):
            form = self.form(**{field: None})
            self.assertFalse(form.is_valid(), f'{field} unchecked must fail')
            self.assertIn(field, form.errors)

    def test_activity_whitelist(self):
        form = self.form(activities=['hacking'])
        self.assertFalse(form.is_valid())
        self.assertIn('activities', form.errors)


# ----------------------------------------------------------------------
# views: GET/POST flows and the mail hook
# ----------------------------------------------------------------------

class ViewTests(MediaRootMixin, TestCase):
    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_get_renders_form_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/apply.html')
        body = response.content.decode()
        # Responsive on phones, branded, with the photo guide visible.
        self.assertIn('viewport', body)
        self.assertIn('form.css', body)
        self.assertIn('Photo guide:', body)
        self.assertIn('max 10 MB', body)
        self.assertIn('Full name (as on your ID)', body)
        # The exact confirmation text from the PDF spec is embedded.
        self.assertIn('unique Ambassador Code', body)

    def test_post_success_ajax_creates_ambassador_and_pending_job(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(
                '/', full_post_payload(), **self.AJAX)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['success'], True)
        self.assertEqual(
            data['message'], 'Application received. Thank you!')

        amb = Ambassador.objects.get(email='applicant@example.com')
        self.assertEqual(amb.name, 'Test Applicant')
        job = MailJob.objects.get(
            campaign='ambassador_received', ambassador=amb)
        self.assertEqual(job.status, MailJob.PENDING)
        self.assertEqual(job.to_email, amb.email)
        # Exactly one background send is queued, after the DB commit.
        self.assertEqual(len(callbacks), 1)
        # Photo stored under media_files/ambassador_photos/.
        saved = Path(self._media_root) / 'ambassador_photos'
        self.assertEqual(len(list(saved.iterdir())), 1)

    def test_post_success_non_ajax_redirects_to_thanks(self):
        response = self.client.post('/', full_post_payload())
        self.assertRedirects(response, '/thanks/')
        self.assertEqual(Ambassador.objects.count(), 1)

    def test_post_duplicate_email_ajax(self):
        make_ambassador(email='applicant@example.com')
        response = self.client.post(
            '/', full_post_payload(), **self.AJAX)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertEqual(data['success'], False)
        self.assertIn('email', data['errors'])
        self.assertIn('already exists', data['errors']['email'][0])
        self.assertEqual(Ambassador.objects.count(), 1)
        self.assertEqual(MailJob.objects.count(), 0)

    def test_post_duplicate_email_race_is_friendly(self):
        """Row inserted between validation and save (concurrent winner):
        the loser must see the friendly duplicate message, never a 500.

        The simulated winner is inserted inside the view's own atomic
        block, so the IntegrityError rollback removes it again - in a
        real race the winner commits in a separate transaction and
        survives. Hence only the response contract is asserted here.
        """
        original_save = AmbassadorForm.save

        def racing_save(form_self):
            make_ambassador(email='applicant@example.com')  # the "winner"
            return original_save(form_self)

        with mock.patch.object(AmbassadorForm, 'save', racing_save):
            response = self.client.post('/', full_post_payload(), **self.AJAX)

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('email', data['errors'])
        self.assertIn('already exists', data['errors']['email'][0])
        self.assertEqual(MailJob.objects.count(), 0)

    def test_post_invalid_ajax_returns_field_errors(self):
        response = self.client.post('/', {}, **self.AJAX)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertEqual(data['success'], False)
        for field in ('name', 'email', 'photo'):
            self.assertIn(field, data['errors'])
        self.assertEqual(Ambassador.objects.count(), 0)

    def test_post_invalid_non_ajax_rerenders_form(self):
        response = self.client.post('/', {})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/apply.html')
        self.assertIn('form', response.context)
        self.assertTrue(response.context['form'].is_bound)

    def test_thanks_page(self):
        response = self.client.get('/thanks/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/thanks.html')

    def test_post_rate_limiting_ajax(self):
        with override_settings(RATE_LIMIT_APPLY_PER_HOUR=2):
            r1 = self.client.post('/', {}, **self.AJAX)
            self.assertEqual(r1.status_code, 400)
            r2 = self.client.post('/', {}, **self.AJAX)
            self.assertEqual(r2.status_code, 400)
            # 3rd request should be blocked with 429
            r3 = self.client.post('/', {}, **self.AJAX)
            self.assertEqual(r3.status_code, 429)
            data = json.loads(r3.content)
            self.assertFalse(data['success'])
            self.assertIn('__all__', data['errors'])
            self.assertIn('Too many submissions', data['errors']['__all__'][0])

    def test_post_rate_limiting_non_ajax(self):
        with override_settings(RATE_LIMIT_APPLY_PER_HOUR=1):
            r1 = self.client.post('/', {})
            self.assertEqual(r1.status_code, 200)
            # 2nd request should be blocked with 429
            r2 = self.client.post('/', {})
            self.assertEqual(r2.status_code, 429)
            self.assertContains(r2, 'Too many submissions', status_code=429)


# ----------------------------------------------------------------------
# admin registration
# ----------------------------------------------------------------------

class AdminTests(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser(
            'ops-admin', 'ops-admin@example.com', 'secret-123')
        self.client.force_login(self.user)

    def test_models_registered(self):
        from .admin import AmbassadorAdmin
        from emails.admin import MailJobAdmin
        self.assertIsInstance(
            django_admin.site._registry[Ambassador], AmbassadorAdmin)
        self.assertIsInstance(
            django_admin.site._registry[MailJob], MailJobAdmin)

    def test_changelists_render(self):
        amb = make_ambassador()
        MailJob.objects.create(
            campaign='ambassador_received', ambassador=amb, to_email=amb.email)
        self.assertEqual(
            self.client.get('/admin/registration/ambassador/').status_code, 200)
        self.assertEqual(
            self.client.get('/admin/emails/mailjob/').status_code, 200)

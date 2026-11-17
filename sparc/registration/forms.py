import os

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from PIL import Image

from .models import Ambassador

# PDF rules for the photo (field 19): JPG or PNG, 1 file, max 10 MB.
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_PHOTO_EXTENSIONS = ('.jpg', '.jpeg', '.png')

# Light format check for the WhatsApp number (field 3, "required"): optional
# leading '+', then digits with spaces/dashes/brackets as separators,
# 7-20 characters in total (matches the model field's max_length).
whatsapp_validator = RegexValidator(
    regex=r'^\+?[0-9][0-9\s\-()]{6,19}$',
    message='Enter a valid WhatsApp number, e.g. +8801712345678.',
)

# PDF section 7: all four agreements are required.
AGREEMENT_FIELDS = (
    'agree_info_accurate',
    'agree_media_usage',
    'agree_points_ranking',
    'agree_contact_consent',
)


class AmbassadorForm(forms.ModelForm):
    """The SPARC Ambassador application form.

    Structure (fields/widgets/labels) was set up in Phase 2; this phase adds
    the validation rules from the PDF spec. The browser-side checks in
    form.js are a courtesy - the server re-enforces every rule here.
    """

    # Model stores a BooleanField, but the PDF wants a Yes/No radio group.
    # TypedChoiceField coerces the string 'True'/'False' back to a real
    # bool - a plain ChoiceField would store the *string* 'False', which is
    # truthy in Python and would corrupt the flag.
    is_ieee_member = forms.TypedChoiceField(
        label='Are you an IEEE member?',
        choices=[('True', 'Yes'), ('False', 'No')],
        coerce=lambda v: v == 'True',
        widget=forms.RadioSelect,
    )

    # Model stores a JSONField; the form exposes it as the PDF's checkbox
    # list. On save the cleaned list is stored as JSON in the model field.
    activities = forms.MultipleChoiceField(
        label='Which activities are you comfortable with?',
        choices=Ambassador.ACTIVITY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Ambassador
        fields = [
            'name', 'email', 'whatsapp', 'date_of_birth', 'gender',
            'university', 'department', 'year_of_study', 'student_id',
            'is_ieee_member', 'ieee_number', 'ieee_grade', 'ieee_branch',
            'ieee_position',
            'photo', 'bio',
            'why_ambassador', 'activities', 'heard_from',
            'agree_info_accurate', 'agree_media_usage',
            'agree_points_ranking', 'agree_contact_consent',
        ]
        widgets = {
            'gender': forms.RadioSelect,
            'heard_from': forms.RadioSelect,
            'year_of_study': forms.Select(attrs={'class': 'input'}),
            'ieee_grade': forms.Select(attrs={'class': 'input'}),
            'photo': forms.ClearableFileInput(attrs={'class': 'file-input'}),
            'name': forms.TextInput(attrs={
                'class': 'input', 'placeholder': 'Exactly as printed on your ID'}),
            'email': forms.EmailInput(attrs={
                'class': 'input', 'placeholder': 'you@example.com'}),
            'whatsapp': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '+8801XXXXXXXXX'}),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'input', 'type': 'date'}),
            'university': forms.TextInput(attrs={'class': 'input'}),
            'department': forms.TextInput(attrs={'class': 'input'}),
            'student_id': forms.TextInput(attrs={'class': 'input'}),
            'ieee_number': forms.TextInput(attrs={'class': 'input'}),
            'ieee_branch': forms.TextInput(attrs={'class': 'input'}),
            'ieee_position': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'Member, Volunteer, Officer, Chairperson...'}),
            'bio': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
            'why_ambassador': forms.Textarea(attrs={'class': 'input', 'rows': 5}),
        }

    # ------------------------------------------------------------------
    # Field-level validation (PDF rules)
    # ------------------------------------------------------------------

    def clean_email(self):
        """PDF rule for field 2: 'Required, valid email, unique'.

        The database unique index is the last line of defence; this gives a
        friendly field-level message. Matching is case-insensitive and the
        value is stored lower-case, so Verify@X.com cannot slip past the
        unique index with different casing.
        """
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and Ambassador.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                'An application with this email address already exists. '
                'All updates will be sent to the original address.')
        return email

    def clean_whatsapp(self):
        whatsapp = (self.cleaned_data.get('whatsapp') or '').strip()
        whatsapp_validator(whatsapp)
        return whatsapp

    def clean_photo(self):
        """PDF rule for field 19: 'JPG or PNG, 1 file, max 10 MB'.

        The browser pre-check in form.js is only a courtesy; everything is
        re-checked here. Content-Type is deliberately NOT trusted (the
        browser sends it and clients can fake it) - the Pillow format check
        below is the reliable verdict.
        """
        photo = self.cleaned_data.get('photo')
        if not photo:
            return photo

        if photo.size > MAX_PHOTO_BYTES:
            raise ValidationError(
                'Photo is too large (%.1f MB). Maximum is 10 MB.'
                % (photo.size / 1048576))

        ext = os.path.splitext(photo.name)[1].lower()
        if ext not in ALLOWED_PHOTO_EXTENSIONS:
            raise ValidationError('Upload a JPG or PNG image.')

        try:
            img = Image.open(photo)
        except Exception:
            raise ValidationError('That file is not a valid image.')
        if img.format not in ('JPEG', 'PNG'):
            raise ValidationError('Upload a JPG or PNG image.')
        img.verify()      # catches corrupted files (truncated data, bad headers)
        photo.seek(0)     # reset the stream: Django re-reads it when saving
        return photo

    def clean_bio(self):
        """PDF rule for field 20: 'Paragraph, max 50 words'.

        str.split() splits on runs of whitespace and ignores leading and
        trailing spaces - the same counting the JavaScript counter uses.
        """
        bio = self.cleaned_data.get('bio') or ''
        word_count = len(bio.split())
        if word_count > 50:
            raise ValidationError(
                'The bio must be 50 words or fewer (you wrote %d).' % word_count)
        return bio

    def clean_activities(self):
        """Defence in depth: MultipleChoiceField already validates against
        its choices; this re-checks against the model's ACTIVITY_CHOICES so
        hand-crafted POSTs cannot smuggle unknown values into the JSON."""
        activities = self.cleaned_data.get('activities')
        if not activities:
            return []
        allowed = {key for key, _ in Ambassador.ACTIVITY_CHOICES}
        if any(item not in allowed for item in activities):
            raise ValidationError('Invalid activity selection.')
        return activities

    # ------------------------------------------------------------------
    # Cross-field validation
    # ------------------------------------------------------------------

    def clean(self):
        cleaned = super().clean()

        # PDF section 3: the four IEEE fields are required only when the
        # applicant answered Yes to "Are you an IEEE member?".
        if cleaned.get('is_ieee_member'):
            for field in ('ieee_number', 'ieee_grade', 'ieee_branch',
                          'ieee_position'):
                if not cleaned.get(field):
                    self.add_error(field, 'This is required for IEEE members.')

        # PDF section 7: all four agreements are required. (The form fields
        # are not required=False-by-default enforced; unchecked boxes simply
        # arrive as False, so we attach one friendly message per box here.)
        for field in AGREEMENT_FIELDS:
            if not cleaned.get(field):
                self.add_error(field, 'You must accept this to continue.')

        return cleaned

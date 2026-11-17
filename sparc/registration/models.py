from django.db import models


class Ambassador(models.Model):
    """One SPARC Ambassador application (one row per form submission).

    Field set mirrors the PDF spec (SPARC Ambassador Application 2026),
    sections 1, 2, 3, 4, 6 and 7. Cross-field rules (IEEE fields required
    only when the applicant is a member, photo type/size, 50-word bio,
    all four agreements ticked) live in registration/forms.py in Phase 3 -
    the database only stores what the validated form hands over.
    """

    # --- Section 1: personal information ---
    GENDER_MALE = 'male'
    GENDER_FEMALE = 'female'
    GENDER_CHOICES = [
        (GENDER_MALE, 'Male'),
        (GENDER_FEMALE, 'Female'),
    ]

    name = models.CharField('Full name (as on your ID)', max_length=120)
    # unique=True also creates the DB index; PDF rule: "Required, valid email, unique".
    email = models.EmailField('Email address (all updates go here)', unique=True)
    whatsapp = models.CharField('WhatsApp number', max_length=20)
    date_of_birth = models.DateField('Date of birth')
    gender = models.CharField('Gender', max_length=10, choices=GENDER_CHOICES)

    # --- Section 2: university information ---
    YEAR_CHOICES = [
        ('1st', '1st'),
        ('2nd', '2nd'),
        ('3rd', '3rd'),
        ('4th', '4th'),
        ('postgraduate', 'Postgraduate'),
    ]

    university = models.CharField('University name', max_length=120)
    department = models.CharField('Department', max_length=120)
    year_of_study = models.CharField(
        'Current year of study', max_length=20, choices=YEAR_CHOICES)
    student_id = models.CharField('Student ID number', max_length=40)

    # --- Section 3: IEEE information (required only if is_ieee_member) ---
    IEEE_GRADE_CHOICES = [
        ('student_member', 'Student Member'),
        ('graduate_student_member', 'Graduate Student Member'),
        ('member', 'Member'),
        ('other', 'Other'),
    ]

    is_ieee_member = models.BooleanField('Are you an IEEE member?', default=False)
    ieee_number = models.CharField('IEEE membership number', max_length=40, blank=True)
    ieee_grade = models.CharField(
        'IEEE membership grade', max_length=30, choices=IEEE_GRADE_CHOICES, blank=True)
    ieee_branch = models.CharField('IEEE Student Branch name', max_length=120, blank=True)
    ieee_position = models.CharField(
        'Your position in the branch, if any',
        max_length=80, blank=True,
        help_text='e.g. Member, Volunteer, Officer, Chairperson.')

    # --- Section 4: photo for website, social media and ID ---
    photo = models.ImageField(
        'Formal photo',
        upload_to='ambassador_photos/',
        help_text='JPG or PNG, 1 file, max 10 MB. Formal attire, plain light '
                  'background, face clearly visible (photo guide is shown on the form).')
    bio = models.TextField(
        'Short bio for the website', help_text='Max 50 words.')

    # --- Section 6: about you ---
    ACTIVITY_CHOICES = [
        ('social_media_posts', 'Social media posts and stories'),
        ('making_short_videos', 'Making short videos'),
        ('hanging_posters', 'Hanging posters on campus'),
        ('talking_to_students', 'Talking to students and societies'),
        ('writing_quotes', 'Writing quotes and captions'),
        ('organizing_sessions', 'Organizing campus sessions'),
    ]
    HEARD_FROM_CHOICES = [
        ('social_media', 'Social media'),
        ('friend', 'Friend'),
        ('ieee_branch', 'IEEE branch'),
        ('university', 'University'),
        ('other', 'Other'),
    ]

    why_ambassador = models.TextField(
        'Why do you want to become a SPARC Ambassador?')
    activities = models.JSONField(
        'Which activities are you comfortable with?',
        default=list, blank=True,
        help_text='List of ACTIVITY_CHOICES keys; validated in the form.')
    heard_from = models.CharField(
        'How did you hear about SPARC?', max_length=20, choices=HEARD_FROM_CHOICES)

    # --- Section 7: agreement (all four required; enforced in the form) ---
    agree_info_accurate = models.BooleanField(
        'I confirm that all the information provided is accurate.', default=False)
    agree_media_usage = models.BooleanField(
        'I agree that SPARC may use my name, photo and bio on its website, '
        'social media and ID card.', default=False)
    agree_points_ranking = models.BooleanField(
        'I understand that points are earned through tasks and ambassadors '
        'are ranked on performance.', default=False)
    agree_contact_consent = models.BooleanField(
        'I agree to be contacted by email and WhatsApp about SPARC activities.',
        default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'ambassador application'
        verbose_name_plural = 'ambassador applications'

    def __str__(self):
        return f'{self.name} <{self.email}>'

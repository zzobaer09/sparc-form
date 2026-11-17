from django import forms

from .models import Ambassador


class AmbassadorForm(forms.ModelForm):
    """The SPARC Ambassador application form.

    Phase 2 scope: fields, widgets and labels only - the template renders
    straight from this form. Phase 3 adds the cross-field validation as
    clean_* methods (IEEE conditionality, photo type/size, 50-word bio,
    all-four-agreements rule, WhatsApp format).
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

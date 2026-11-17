from django.contrib import admin
from django.utils.html import format_html

from .models import Ambassador


@admin.register(Ambassador)
class AmbassadorAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'photo_thumbnail', 'name', 'email', 'university',
        'year_of_study', 'is_ieee_member', 'created_at')
    list_filter = ('year_of_study', 'gender', 'is_ieee_member', 'heard_from', 'created_at')
    search_fields = ('name', 'email', 'university', 'department', 'student_id')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'photo_thumbnail')
    fieldsets = (
        ('Section 1 - Personal information', {
            'fields': ('name', 'email', 'whatsapp', 'date_of_birth', 'gender'),
        }),
        ('Section 2 - University information', {
            'fields': ('university', 'department', 'year_of_study', 'student_id'),
        }),
        ('Section 3 - IEEE information', {
            'fields': ('is_ieee_member', 'ieee_number', 'ieee_grade',
                       'ieee_branch', 'ieee_position'),
        }),
        ('Section 4 - Photo for website, social media and ID', {
            'fields': ('photo', 'photo_thumbnail', 'bio'),
        }),
        ('Section 6 - About you', {
            'fields': ('why_ambassador', 'activities', 'heard_from'),
        }),
        ('Section 7 - Agreement (all four required)', {
            'fields': ('agree_info_accurate', 'agree_media_usage',
                       'agree_points_ranking', 'agree_contact_consent'),
        }),
        ('Timestamps', {'fields': ('created_at',)}),
    )

    @admin.display(description='Photo')
    def photo_thumbnail(self, obj):
        if obj and obj.photo:
            return format_html(
                '<img src="{}" style="max-height:120px;border-radius:6px">',
                obj.photo.url)
        return '-'

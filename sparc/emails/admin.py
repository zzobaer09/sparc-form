from django.contrib import admin
from django.utils.html import format_html

from .models import MailJob


@admin.register(MailJob)
class MailJobAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'campaign', 'ambassador_name', 'to_email', 'status_badge',
        'gmail_message_id', 'created_at', 'sent_at')
    list_filter = ('status', 'campaign')
    search_fields = ('to_email', 'ambassador__name', 'ambassador__email', 'gmail_message_id')
    # The mail ledger is system-managed: the sender and send_pending write
    # status/error/message-id. Admin can edit campaign/ambassador/to_email
    # and flip status manually, but never the delivery record itself.
    readonly_fields = ('error', 'gmail_message_id', 'created_at', 'sent_at')
    actions = ('retry_selected',)

    @admin.display(description='Ambassador', ordering='ambassador__name')
    def ambassador_name(self, obj):
        return obj.ambassador.name

    @admin.display(description='Status', ordering='status')
    def status_badge(self, obj):
        colors = {
            MailJob.SENT: '#1a7f37',
            MailJob.FAILED: '#cf222e',
            MailJob.PENDING: '#9a6700',
        }
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.status, '#57606a'), obj.status)

    @admin.action(
        description='Retry selected: reset Failed jobs to Pending '
                    '(send_pending will pick them up)')
    def retry_selected(self, request, queryset):
        # Never touch SENT jobs - the PDF rule is "never send twice".
        updated = queryset.filter(status=MailJob.FAILED).update(
            status=MailJob.PENDING, error='')
        if updated:
            self.message_user(request, f'{updated} failed job(s) reset to Pending.')
        else:
            self.message_user(request, 'No failed jobs in selection - nothing reset.')

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import MailJob
from .sender import build_service, process_job


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
            MailJob.SENDING: '#0969da',
        }
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.status, '#57606a'), obj.status)

    @admin.action(
        description='Send now: process Pending/Failed jobs via the Gmail API')
    def retry_selected(self, request, queryset):
        """Manual retry from the admin: build one service, then run each
        selected job through process_job (which skips already-sent jobs)."""
        try:
            service = build_service()
        except RuntimeError as exc:
            self.message_user(
                request, f'Cannot send now: {exc}', level=messages.ERROR)
            return

        sent = failed = 0
        for job in queryset.exclude(status=MailJob.SENT).order_by('pk'):
            result = process_job(job.id, service)
            if result is None:
                continue                # job row vanished mid-run
            if result.status == MailJob.SENT:
                sent += 1
            else:
                failed += 1
        if sent or failed:
            self.message_user(
                request, f'Send now finished: {sent} sent, {failed} failed.')
        else:
            self.message_user(
                request, 'Nothing to send - selection contains only '
                         'already-sent jobs.')

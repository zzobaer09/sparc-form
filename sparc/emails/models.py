from django.db import models


class MailJob(models.Model):
    """One outgoing email tied to one ambassador for one campaign.

    Fields and the one_mail_per_campaign constraint are taken verbatim from
    the PDF spec. Lifecycle: pending -> sent (gmail_message_id filled in)
    or failed (error filled in). A failed job never loses the application;
    the send_pending command (Phase 5) re-sends pending and failed jobs.
    """

    PENDING, SENT, FAILED = 'pending', 'sent', 'failed'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (SENT, 'Sent'),
        (FAILED, 'Failed'),
    ]

    campaign = models.CharField(max_length=40)
    ambassador = models.ForeignKey(
        'registration.Ambassador', on_delete=models.CASCADE)
    to_email = models.EmailField()
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=PENDING)
    error = models.TextField(blank=True)
    gmail_message_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['campaign', 'ambassador'], name='one_mail_per_campaign')]
        ordering = ['created_at']

    def __str__(self):
        return f'{self.campaign} -> {self.to_email} ({self.status})'

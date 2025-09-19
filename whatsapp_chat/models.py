# whatsapp_chat/models.py
from django.db import models


class ChatMessage(models.Model):
    # Inbound (from Twilio webhook)
    message_sid = models.CharField(max_length=64, db_index=True)
    account_sid = models.CharField(max_length=64, blank=True, null=True)
    sms_status = models.CharField(max_length=32, blank=True, null=True)
    message_type = models.CharField(max_length=32, blank=True, null=True)
    num_media = models.IntegerField(default=0)
    num_segments = models.IntegerField(default=1)
    wa_id = models.CharField(max_length=32, blank=True, null=True)
    profile_name = models.CharField(max_length=128, blank=True, null=True)
    api_version = models.CharField(max_length=16, blank=True, null=True)
    channel_metadata = models.JSONField(blank=True, null=True)

    # Phones & text
    from_phone = models.CharField(max_length=32, db_index=True)  # whatsapp:+91...
    to_phone = models.CharField(max_length=32, db_index=True)
    user_text = models.TextField(blank=True, null=True)

    # Gemini output + metrics
    response_text = models.TextField(blank=True, null=True)
    model_name = models.CharField(max_length=64, default="gemini-1.5-flash")
    temperature = models.FloatField(default=0.2)
    latency_ms = models.IntegerField(default=0)

    # Outbound send (REST API)
    outbound_message_sid = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    delivery_status = models.CharField(max_length=32, blank=True, null=True)  # queued/sent/delivered/failed
    delivery_error_code = models.CharField(max_length=32, blank=True, null=True)
    delivery_error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.from_phone} → {self.to_phone} | {self.created_at:%Y-%m-%d %H:%M}"

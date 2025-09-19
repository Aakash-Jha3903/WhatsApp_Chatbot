# whatsapp_chat/admin.py
from django.contrib import admin
from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "user_text","created_at", "from_phone", "to_phone",
        "message_sid", "outbound_message_sid",
        "delivery_status", "latency_ms",
    )
    search_fields = ("from_phone", "to_phone", "message_sid", "outbound_message_sid", "user_text", "response_text")
    list_filter = ("delivery_status", "sms_status", "model_name", "created_at")
    readonly_fields = ("created_at",)


# whatsapp_chat/urls.py
from django.urls import path
from .views import (
    HealthView,
    WhatsAppWebhookView,
    StatusCallbackView,
    ChatMessageListView,
    ChatMessageCSVExport,
)

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    
    path("webhook", WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
    
    path("status", StatusCallbackView.as_view(), name="twilio-status"),
    path("messages", ChatMessageListView.as_view(), name="messages-list"),
    path("save_messages_csv", ChatMessageCSVExport.as_view(), name="messages-csv"),
]


"""
GET   http://127.0.0.1:8000/whatsapp_chat/health


POST  http://127.0.0.1:8000/whatsapp_chat/status


GET   http://127.0.0.1:8000/whatsapp_chat/messages


GET   http://127.0.0.1:8000/whatsapp_chat/save_messages_csv
"""

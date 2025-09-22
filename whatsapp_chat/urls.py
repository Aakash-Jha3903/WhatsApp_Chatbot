# whatsapp_chat/urls.py
from django.urls import path
from .views import ( HealthView, WhatsAppWebhookView, StatusCallbackView, ChatMessageListView, ChatMessageCSVExport, 
                        # ConvertHtml2PDFWeasyView
                        SendImageView, SendPDFView,ConvertHtml2PDF, 
                    )

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),

    path("webhook", WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
    path("status", StatusCallbackView.as_view(), name="twilio-status"),

    path("messages", ChatMessageListView.as_view(), name="messages-list"),
    path("save_messages_csv", ChatMessageCSVExport.as_view(), name="messages-csv"),

    path("send_image", SendImageView.as_view(), name="send-image"),
    path("send_pdf", SendPDFView.as_view(), name="send-pdf"),

    path("convert_Html2PDF", ConvertHtml2PDF.as_view(), name="generate-report-pdf"),

    # path("generate_report_pdf_weasy", GenerateReportPDFWeasyView.as_view(), name="generate-report-pdf-weasy"),
    
    
]



"""
GET   http://127.0.0.1:8000/whatsapp_chat/health


POST  http://127.0.0.1:8000/whatsapp_chat/status


GET   http://127.0.0.1:8000/whatsapp_chat/messages


GET   http://127.0.0.1:8000/whatsapp_chat/save_messages_csv


POST  http://127.0.0.1:8000/whatsapp_chat/send_image
{
    "to": "whatsapp:+91xxxxxxxx",
    "image_url": "https://images.pexels.com/photos/40185/mac-freelancer-macintosh-macbook-40185.jpeg?cs=srgb&dl=pexels-pixabay-40185.jpg&fm=jpg",
    "caption": "Here you go!"
}


POST  http://127.0.0.1:8000/whatsapp_chat/send_pdf
{
    "to": "whatsapp:+91XXXXXXXXXX",
    "pdf_url": "https://pdfobject.com/pdf/sample.pdf",
    "caption": "Sample PDF via sandbox"
}
"""

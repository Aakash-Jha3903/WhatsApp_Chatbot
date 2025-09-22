import csv
import json
import os
from datetime import datetime, timedelta

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils.timezone import make_aware
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from twilio.rest import Client

from .models import ChatMessage
from .serializers import ChatMessageSerializer
from .gemini_client import ask_gemini, MODEL_NAME, TEMPERATURE



class ChatMessageListView(generics.ListAPIView):
    """Read-only list for dashboards/QA with simple filters."""
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.AllowAny]  # no auth (dev)

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params

        if fp := q.get("from_phone"):
            qs = qs.filter(from_phone=fp)
        if tp := q.get("to_phone"):
            qs = qs.filter(to_phone=tp)

        # start / end filters (YYYY-MM-DD or ISO datetime)
        start = q.get("start")
        end = q.get("end")
        if start:
            try:
                dt = parse_datetime(start) or datetime.fromisoformat(start)
                qs = qs.filter(created_at__gte=make_aware(dt))
            except Exception:
                pass
        if end:
            try:
                dt = parse_datetime(end) or datetime.fromisoformat(end)
                if len(end) == 10:  # if only date provided, include whole day
                    dt = dt + timedelta(days=1)
                qs = qs.filter(created_at__lt=make_aware(dt))
            except Exception:
                pass

        return qs


class ChatMessageCSVExport(APIView):
    """Export all messages (apply your own filters if needed)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        qs = ChatMessage.objects.order_by("-created_at")

        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="chatmessages.csv"'
        w = csv.writer(resp)
        w.writerow([
            "created_at", "from_phone", "to_phone", "user_text",
            "response_text", "latency_ms", "delivery_status",
            "message_sid", "outbound_message_sid"
        ])
        for m in qs:
            w.writerow([
                m.created_at.isoformat(timespec="seconds"),
                m.from_phone, m.to_phone,
                (m.user_text or "").replace("\n", " "),
                (m.response_text or "").replace("\n", " "),
                m.latency_ms, m.delivery_status or "",
                m.message_sid or "", m.outbound_message_sid or "",
            ])

        # optional: also save the CSV on disk (dev convenience)
        save_path = os.path.join(settings.BASE_DIR, "chatmessages.csv")
        with open(save_path, "w", newline="", encoding="utf-8") as f:
            f.write(resp.content.decode("utf-8"))

        return resp


@method_decorator(csrf_exempt, name="dispatch")
class HealthView(APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, *args, **kwargs):
        return Response({"ok": True})


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(APIView):
    """Twilio → our server. We answer with Gemini, save, then send reply via REST API."""
    authentication_classes, permission_classes = [], [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        data = request.data

        user_text    = (data.get("Body") or "").strip()
        from_phone   = data.get("From") or ""               # whatsapp:+91xxxx
        to_phone     = data.get("To") or ""                 # whatsapp:+14xxxx
        message_sid  = data.get("MessageSid") or data.get("SmsMessageSid") or ""
        account_sid  = data.get("AccountSid") or ""
        sms_status   = data.get("SmsStatus") or ""
        message_type = data.get("MessageType") or ""
        num_media    = int(data.get("NumMedia") or 0)
        num_segments = int(data.get("NumSegments") or 1)
        wa_id        = data.get("WaId") or ""
        profile_name = data.get("ProfileName") or ""
        api_version  = data.get("ApiVersion") or ""
        meta_raw     = data.get("ChannelMetadata")

        try:
            channel_metadata = json.loads(meta_raw) if meta_raw else None
        except Exception:
            channel_metadata = {"raw": meta_raw}

        # 1) Ask Gemini
        reply_text, latency_ms = ask_gemini(user_text)

        # 2) Persist inbound + our response
        cm = ChatMessage.objects.create(
            message_sid=message_sid,
            account_sid=account_sid,
            sms_status=sms_status,
            message_type=message_type,
            num_media=num_media,
            num_segments=num_segments,
            wa_id=wa_id,
            profile_name=profile_name,
            api_version=api_version,
            channel_metadata=channel_metadata,
            from_phone=from_phone,
            to_phone=to_phone,
            user_text=user_text,
            response_text=reply_text,
            model_name=MODEL_NAME,
            temperature=TEMPERATURE,
            latency_ms=latency_ms,
        )

        # 3) Send reply via Twilio REST API (explicit enqueue)
        status_cb_url = request.build_absolute_uri(reverse("twilio-status"))
        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            msg = client.messages.create(
                from_=settings.WHATSAPP_FROM,  # e.g., 'whatsapp:+141xxxxxx'
                to=from_phone,
                body=reply_text,
                status_callback=status_cb_url,
            )
            cm.outbound_message_sid = msg.sid
            cm.delivery_status = "queued"
            cm.save(update_fields=["outbound_message_sid", "delivery_status"])
        except Exception as e:
            cm.delivery_status = "failed"
            cm.delivery_error_message = f"{type(e).__name__}: {e}"
            cm.save(update_fields=["delivery_status", "delivery_error_message"])

        # 4) Minimal TwiML response
        return Response("<Response/>", content_type="application/xml")


@method_decorator(csrf_exempt, name="dispatch")
class StatusCallbackView(APIView):
    """Twilio delivery status: queued/sent/delivered/failed."""
    authentication_classes, permission_classes = [], [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        return self._save_status(request)

    def post(self, request, *args, **kwargs):
        return self._save_status(request)

    def _save_status(self, request):
        data = request.query_params if request.method == "GET" else request.data
        outbound_sid = data.get("MessageSid") or data.get("SmsSid") or ""
        status       = data.get("MessageStatus") or data.get("SmsStatus") or ""
        to_phone     = data.get("To") or ""
        from_phone   = data.get("From") or ""
        error_code   = data.get("ErrorCode")
        error_msg    = data.get("ErrorMessage")

        cm = None
        if outbound_sid:
            cm = ChatMessage.objects.filter(outbound_message_sid=outbound_sid).first()
        if not cm:  # fallback by conversation
            cm = (ChatMessage.objects
                  .filter(from_phone=from_phone, to_phone=to_phone)
                  .order_by("-created_at")
                  .first())

        if cm:
            cm.delivery_status = status or cm.delivery_status
            cm.delivery_error_code = error_code or cm.delivery_error_code
            cm.delivery_error_message = error_msg or cm.delivery_error_message
            cm.save(update_fields=["delivery_status", "delivery_error_code", "delivery_error_message"])

        return Response("OK")


# ---------- ad-hoc senders (image/pdf by URL) ----------
class SendImageView(APIView):
    """
    POST /send_image
    JSON: 
    {   
        "to": "whatsapp:+91XXXXXXXXXX",
        "image_url": "https://images.pexels.com/photos/40185/mac-freelancer-macintosh-macbook-40185.jpeg?cs=srgb&dl=pexels-pixabay-40185.jpg&fm=jpg",
        "caption": "Here you go!" 
    }
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        to = request.data.get("to", "")
        image_url = request.data.get("image_url", "")
        caption = request.data.get("caption", "")

        if not (to.startswith("whatsapp:+") and image_url.startswith("https://")):
            return Response({"ok": False, "error": "Provide to=whatsapp:+<number> and a public https image_url"}, status=400)

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        status_cb = request.build_absolute_uri("/status")

        msg = client.messages.create(
            from_=settings.WHATSAPP_FROM,
            to=to,
            body=caption or None,
            media_url=[image_url],
            status_callback=status_cb,
        )
        return Response({"ok": True, "sid": msg.sid})


class SendPDFView(APIView):
    """
    POST /send_pdf
    JSON: 
    {
      "to": "whatsapp:+91XXXXXXXXXX",
      "pdf_url": "https://pdfobject.com/pdf/sample.pdf",
      "caption": "Monthly report"
    }
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        to = request.data.get("to", "")
        pdf_url = request.data.get("pdf_url", "")
        caption = request.data.get("caption", "")

        if not (to.startswith("whatsapp:+") and pdf_url.startswith("https://") and pdf_url.lower().endswith(".pdf")):
            return Response(
                {"ok": False, "error": "Provide to=whatsapp:+<number> and a public https PDF url ending with .pdf"},
                status=400,
            )

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        status_cb = request.build_absolute_uri("/status")

        msg = client.messages.create(
            from_=settings.WHATSAPP_FROM,
            to=to,
            body=caption or None,
            media_url=[pdf_url],
            status_callback=status_cb,
        )
        return Response({"ok": True, "sid": msg.sid})

import re
import pdfkit
# map only the emojis you use (add more as needed)
TWMAP = {
    "🛍️": "1f6cd",            # shopping bags
    "📈": "1f4c8",
    "🚀": "1f680",
    "⏱️": "23f1",
    "⚖️": "2696",
    "📊": "1f4ca",
    "👥": "1f465",
    "🛒": "1f6d2",
    "🆕": "1f195",
    "🔁": "1f501",
    "❌": "274c",
    "👤": "1f464",
    "💰": "1f4b0",
    "📦": "1f4e6",
    "🚶": "1f6b6",
    "♻️": "267b",
    "🔒": "1f512",
    "✨": "2728",
    # complex ZWJ/skin-tone sequence used in your header:
    "🧑🏻‍💻": "1f9d1-1f3fb-200d-1f4bb",
}

_TW_BASE = "https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg"

# compile regex of the keys for fast replacement
_EMOJI_RE = re.compile("|".join(map(re.escape, sorted(TWMAP, key=len, reverse=True))))

def _emoji_to_img(m):
    cp = TWMAP[m.group(0)]
    return (
        f'<img src="{_TW_BASE}/{cp}.svg" '
        f'width="40" height="20" '
        f'style="vertical-align:-2px; margin-right:6px;" '
        f'loading="lazy" alt="">'
    )

def _twemoji(html: str) -> str:
    return _EMOJI_RE.sub(_emoji_to_img, html)

class ConvertHtml2PDF(APIView):
    """
    POST /whatsapp_chat/generate_report_pdf
    Generates a PDF from email_content and saves it under media/reports/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from .one1 import email_content  # your HTML in py string variable (email_content="html content...")

        reports_dir = os.path.join(settings.MEDIA_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        file_name = f"daily_report_{ts}.pdf"
        pdf_path = os.path.join(reports_dir, file_name)

        # 1) Replace emojis with Twemoji SVG <img> tags
        html_with_twemoji = _twemoji(email_content)

        # # 2) Wrap and style (keep your fonts; emojis are images now)
        full_html = f"""<!doctype html>
                        <html>
                        <head>
                          <meta charset="utf-8">
                          <style>
                            body {{ font-family: Arial, sans-serif; }}
                            table {{ border-collapse: collapse; }}
                          </style>
                        </head>
                        <body>
                        {html_with_twemoji}
                        </body>
                        </html>
                    """
        
        ## Alternative: if we want to remove all borders from tables ::::
        # full_html = f"""<!doctype html>
        #                 <html>
        #                 <head>
        #                   <meta charset="utf-8">
        #                   <style>
        #                     /* Emoji already handled; now kill borders coming from inline styles */
        #                     html, body {{ font-family: Arial, sans-serif; }}
        #                     table {{ border-collapse: separate; border-spacing: 0; }}
        #                     table, tr, td, th {{ border: 0 !important; }}
        #                     tr {{ border-bottom: 0 !important; }}
        #                     td {{ border-top: 0 !important; }}
        #                     /* optional: subtle divider instead of borders
        #                     tr + tr td {{ 
        #                       background: linear-gradient(to bottom, rgba(0,0,0,.08), rgba(0,0,0,.08)) 
        #                                   left bottom/100% 1px no-repeat; 
        #                     }} */
        #                   </style>
        #                 </head>
        #                 <body>
        #                 {html_with_twemoji}  <!-- or your email_content if not using Twemoji -->
        #                 </body>
        #                 </html> 
        #             """
                
        options = {
            "encoding": "UTF-8",
            "enable-local-file-access": None,
            "page-size": "A4",
            "margin-top": "10mm",
            "margin-right": "10mm",
            "margin-bottom": "10mm",
            "margin-left": "10mm",
        }

        exe = os.getenv("WKHTMLTOPDF_PATH", r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")
        config = pdfkit.configuration(wkhtmltopdf=exe) if os.path.exists(exe) else None

        ok = pdfkit.from_string(full_html, pdf_path, options=options, configuration=config)
        if not ok:
            return Response({"ok": False, "error": "PDF generation failed"}, status=500)

        rel = os.path.relpath(pdf_path, settings.MEDIA_ROOT)
        return Response({"ok": True, "pdf_path": f"/media/{rel}"})


# # views.py  (only the WeasyPrint view shown) ---------------------------------------------
# class ConvertHtml2PDFWeasyView(APIView):
#     permission_classes = [permissions.AllowAny]

#     def post(self, request):
#         # Ensure Windows loader finds MSYS2 DLLs
#         if os.name == "nt":
#             # allow override via env, else default to MSYS2 UCRT64
#             dll_dir = os.getenv("WEASYPRINT_DLL_DIR", r"C:\msys64\ucrt64\bin")
#             try:
#                 os.add_dll_directory(dll_dir)
#             except FileNotFoundError:
#                 pass

#         # Import AFTER adding DLL directory
#         from weasyprint import HTML

#         from .one1 import email_content

#         reports_dir = os.path.join(settings.MEDIA_ROOT, "reports")
#         os.makedirs(reports_dir, exist_ok=True)

#         ts = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
#         out_path = os.path.join(reports_dir, f"daily_report_weasy_{ts}.pdf")

#         full_html = f"""<!doctype html>
#                         <html>
#                         <head>
#                           <meta charset="utf-8">
#                           <style>
#                             html, body, table, td, span, h1, h2, h3, h4, h5, h6 {{
#                               font-family: "Segoe UI Emoji","Noto Color Emoji","Apple Color Emoji","Segoe UI","Arial",sans-serif;
#                             }}
#                             table {{ border-collapse: collapse; }}
#                           </style>
#                         </head>
#                         <body>
#                         {email_content}
#                         </body>
#                         </html> 
#                     """

#         base_url = request.build_absolute_uri("/")
#         HTML(string=full_html, base_url=base_url).write_pdf(target=out_path)

#         rel = os.path.relpath(out_path, settings.MEDIA_ROOT)
#         return Response({"ok": True, "pdf_path": f"/media/{rel}"})

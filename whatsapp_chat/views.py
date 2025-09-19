# whatsapp_chat/views.py
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
        # save the .csv file in the server (optional)
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

        # 4) Return minimal TwiML so Twilio knows webhook succeeded
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
        if not cm:  # fallback heuristic by conversation
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

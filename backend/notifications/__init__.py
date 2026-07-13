"""
SentinelAI Notification Services

Provides alert delivery via multiple channels:
- WhatsApp (Twilio)
- Phone Calls (Twilio) - Emergency escalation
- SMS (planned)
- Email (planned)
- Push notifications (planned)
"""

from .whatsapp import (
    send_whatsapp_alert,
    send_whatsapp_alert_async,
    send_whatsapp_alert_nonblocking,
    format_alert_message,
    is_whatsapp_configured,
)

from .phone_call import (
    trigger_call_alert,
    trigger_call_alert_nonblocking,
    record_high_alert,
    get_alert_stats,
    is_phone_configured,
)

__all__ = [
    # WhatsApp
    "send_whatsapp_alert",
    "send_whatsapp_alert_async",
    "send_whatsapp_alert_nonblocking",
    "format_alert_message",
    "is_whatsapp_configured",
    # Phone Call
    "trigger_call_alert",
    "trigger_call_alert_nonblocking",
    "record_high_alert",
    "get_alert_stats",
    "is_phone_configured",
]

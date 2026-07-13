"""
SentinelAI WhatsApp Notification Module

Integrates with Twilio WhatsApp Sandbox to send real-time alerts
when incidents are detected.

Usage:
    from notifications.whatsapp import send_whatsapp_alert_nonblocking, format_alert_message
    
    # Format the message
    message = format_alert_message(
        zone="Corridor",
        event_type="Fight",
        confidence=0.87,
        camera_id="cam1"
    )
    
    # Send non-blocking (fire-and-forget)
    send_whatsapp_alert_nonblocking(message)

Environment Variables Required:
    TWILIO_ACCOUNT_SID     - Twilio Account SID
    TWILIO_AUTH_TOKEN      - Twilio Auth Token  
    TWILIO_WHATSAPP_FROM   - Sender WhatsApp number (e.g., whatsapp:+14155238886)
    TWILIO_WHATSAPP_TO     - Recipient WhatsApp number (e.g., whatsapp:+91XXXXXXXXXX)
    TWILIO_WHATSAPP_TEMPLATE_SID - Optional Content Template SID (e.g., HXxxxx)
    TWILIO_WHATSAPP_TEMPLATE_VARS - Optional JSON string for template variables
    WHATSAPP_ALERTS_ENABLED - Set to 'true' to enable alerts (default: false)

Fallback Variables (optional):
    TWILIO_FALLBACK_ACCOUNT_SID
    TWILIO_FALLBACK_AUTH_TOKEN
    TWILIO_FALLBACK_WHATSAPP_FROM
    TWILIO_FALLBACK_WHATSAPP_TO
    TWILIO_FALLBACK_WHATSAPP_TEMPLATE_SID
    TWILIO_FALLBACK_WHATSAPP_TEMPLATE_VARS
    WHATSAPP_FALLBACK_ENABLED
"""

import os
import logging
import threading
import asyncio
import time
import base64
from datetime import datetime
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

# OpenAI for AI-powered summaries
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Initialize logger
logger = logging.getLogger(__name__)

# Thread pool for non-blocking sends
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whatsapp_")
logger.info(f"✅ WhatsApp thread pool initialized (max 2 workers)")

# OpenAI configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_VISION_ENABLED = os.getenv("OPENAI_VISION_ENABLED", "true").lower() in ("true", "1", "yes", "on")

# Initialize OpenAI client if available
_openai_client = None
if OPENAI_AVAILABLE and OPENAI_API_KEY:
    try:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info(f"✅ OpenAI client initialized (model: {OPENAI_MODEL})")
    except Exception as e:
        logger.warning(f"⚠️ Failed to initialize OpenAI client: {e}")
        OPENAI_AVAILABLE = False
elif not OPENAI_API_KEY:
    logger.info("ℹ️ OpenAI API key not configured, AI summaries disabled")
else:
    logger.warning("⚠️ OpenAI package not installed, AI summaries disabled")


# ============================================================================
# AI-POWERED SUMMARY GENERATION
# ============================================================================

def generate_ai_summary(
    zone: str,
    event_type: str,
    confidence: float,
    snapshot_path: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Generate a detailed AI summary of the alert using OpenAI Vision API.
    
    Analyzes the snapshot image (if available) and event context to create
    a comprehensive description of what happened.
    
    Args:
        zone: Detection zone
        event_type: Type of event detected
        confidence: Detection confidence (0.0 - 1.0)
        snapshot_path: Path to the snapshot image file
        metadata: Additional event metadata
    
    Returns:
        AI-generated summary string, or None if generation fails
    """
    if not _openai_client or not OPENAI_VISION_ENABLED:
        return None
    
    if not snapshot_path or not Path(snapshot_path).exists():
        logger.debug("No snapshot available for AI analysis")
        return None
    
    try:
        # Read and encode the image
        with open(snapshot_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode('utf-8')
        
        # Build the prompt for GPT-4o-mini
        event_display = event_type.replace("_", " ").title()
        prompt = f"""You are an AI security analyst for SentinelAI, a school security monitoring system.

Analyze this security footage snapshot and provide a brief, clear summary (2-3 sentences) of what you observe.

Context:
- Location: {zone}
- Detected Event: {event_display}
- Confidence: {confidence:.0%}
- Additional Info: {metadata if metadata else 'None'}

Focus on:
1. What is happening in the image
2. Any potential security concerns
3. Recommended actions if necessary

Keep the summary professional, concise, and actionable for school security personnel."""

        # Call OpenAI Vision API
        response = _openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}",
                                "detail": "low"  # Use low detail for faster/cheaper processing
                            }
                        }
                    ]
                }
            ],
            max_tokens=200,
            temperature=0.3,  # Lower temperature for more factual responses
        )
        
        ai_summary = response.choices[0].message.content.strip()
        logger.info(f"✅ AI summary generated for {event_type} (length: {len(ai_summary)} chars)")
        return ai_summary
        
    except Exception as e:
        logger.error(f"Failed to generate AI summary: {e}")
        return None


# ============================================================================
# DEDUPLICATION / COOLDOWN MANAGER
# ============================================================================

class WhatsAppCooldownManager:
    """
    Prevents duplicate WhatsApp alerts by enforcing per-camera cooldowns.
    
    Features:
    - ONE alert per camera within the cooldown period
    - Alert counter: Tracks alerts per camera
    - Threshold trigger: After 6+ alerts, enforces extended cooldown
    - Prevents alert flooding and duplicate notifications
    """
    
    def __init__(self, cooldown_seconds: float = 30.0, alert_threshold: int = 6):
        """
        Args:
            cooldown_seconds: Minimum time between alerts for the same camera
            alert_threshold: Number of alerts to trigger extended cooldown (default: 6)
        """
        self._cooldown = cooldown_seconds
        self._alert_threshold = alert_threshold
        self._last_alert_time: Dict[str, float] = {}  # camera_id -> timestamp
        self._alert_count: Dict[str, int] = {}  # camera_id -> alert count
        self._threshold_triggered: Dict[str, float] = {}  # camera_id -> threshold_trigger_time
        self._lock = threading.Lock()
    
    def can_send(self, camera_id: str) -> bool:
        """
        Check if an alert can be sent for this camera.
        
        Args:
            camera_id: Camera identifier
        
        Returns:
            True if enough time has passed since last alert for this camera
        """
        with self._lock:
            now = time.time()
            last_time = self._last_alert_time.get(camera_id, 0.0)
            return (now - last_time) >= self._cooldown
    
    def mark_sent(self, camera_id: str) -> None:
        """Mark that an alert was sent for this camera."""
        with self._lock:
            self._last_alert_time[camera_id] = time.time()
    
    def should_send(self, camera_id: str) -> bool:
        """
        Check and atomically mark if alert should be sent.
        
        This combines can_send() and mark_sent() atomically to prevent races.
        Implements two-tier system:
        1. One alert per cooldown period (30s)
        2. Extended cooldown after 6+ alerts to prevent spam
        
        Args:
            camera_id: Camera identifier
        
        Returns:
            True if alert should be sent (and marks it), False if cooldown active
        """
        with self._lock:
            now = time.time()
            last_time = self._last_alert_time.get(camera_id, 0.0)
            alert_count = self._alert_count.get(camera_id, 0)
            threshold_time = self._threshold_triggered.get(camera_id, 0.0)
            
            # Check if in extended cooldown (after 6+ alerts)
            if alert_count >= self._alert_threshold and (now - threshold_time) < self._cooldown * 2:
                return False
            
            # Check if in normal cooldown
            if (now - last_time) < self._cooldown:
                return False
            
            # Can send! Update tracking
            self._last_alert_time[camera_id] = now
            self._alert_count[camera_id] = alert_count + 1
            
            # Trigger extended cooldown if threshold reached
            if self._alert_count[camera_id] >= self._alert_threshold:
                self._threshold_triggered[camera_id] = now
                logger.warning(
                    f"[WHATSAPP_THRESHOLD] Camera {camera_id} has reached {self._alert_count[camera_id]} alerts. "
                    f"Activating extended cooldown (60s) to prevent spam."
                )
            
            return True
    
    def get_remaining_cooldown(self, camera_id: str) -> float:
        """Get remaining cooldown time in seconds for a camera."""
        with self._lock:
            now = time.time()
            last_time = self._last_alert_time.get(camera_id, 0.0)
            remaining = self._cooldown - (now - last_time)
            return max(0.0, remaining)

    def get_alert_count(self, camera_id: str) -> int:
        """Get current alert count for a camera."""
        with self._lock:
            return self._alert_count.get(camera_id, 0)

    def is_threshold_active(self, camera_id: str) -> bool:
        """Check if extended cooldown (threshold) is active for a camera."""
        with self._lock:
            now = time.time()
            threshold_time = self._threshold_triggered.get(camera_id, 0.0)
            alert_count = self._alert_count.get(camera_id, 0)
            return alert_count >= self._alert_threshold and (now - threshold_time) < self._cooldown * 2
    
    def reset(self, camera_id: Optional[str] = None) -> None:
        """Reset cooldown state for a camera or all cameras."""
        with self._lock:
            if camera_id:
                self._last_alert_time.pop(camera_id, None)
            else:
                self._last_alert_time.clear()


def _parse_template_vars(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("WhatsApp template vars are not valid JSON. Ignoring.")
        return {}


def _get_primary_config() -> Dict[str, Any]:
    """Get primary Twilio configuration from environment variables."""
    return {
        "name": "primary",
        "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "auth_token": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "from_number": os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"),
        "to_number": os.getenv("TWILIO_WHATSAPP_TO", ""),
        "template_sid": os.getenv("TWILIO_WHATSAPP_TEMPLATE_SID", ""),
        "template_vars": _parse_template_vars(os.getenv("TWILIO_WHATSAPP_TEMPLATE_VARS", "")),
        "enabled": os.getenv("WHATSAPP_ALERTS_ENABLED", "false").lower() in ("true", "1", "yes", "on"),
    }


def _get_fallback_config() -> Dict[str, Any]:
    """Get fallback Twilio configuration from environment variables."""
    return {
        "name": "fallback",
        "account_sid": os.getenv("TWILIO_FALLBACK_ACCOUNT_SID", ""),
        "auth_token": os.getenv("TWILIO_FALLBACK_AUTH_TOKEN", ""),
        "from_number": os.getenv("TWILIO_FALLBACK_WHATSAPP_FROM", ""),
        "to_number": os.getenv("TWILIO_FALLBACK_WHATSAPP_TO", ""),
        "template_sid": os.getenv("TWILIO_FALLBACK_WHATSAPP_TEMPLATE_SID", ""),
        "template_vars": _parse_template_vars(os.getenv("TWILIO_FALLBACK_WHATSAPP_TEMPLATE_VARS", "")),
        "enabled": os.getenv("WHATSAPP_FALLBACK_ENABLED", "false").lower() in ("true", "1", "yes", "on"),
    }


def _is_config_valid(config: Dict[str, Any]) -> bool:
    if not config.get("enabled"):
        return False
    required = [config.get("account_sid"), config.get("auth_token"), config.get("to_number")]
    return all(required)


def _is_valid_template_sid(template_sid: str) -> bool:
    if not template_sid:
        return False
    return template_sid.startswith(("HX", "TM", "WH"))

# Global cooldown manager - 30 second cooldown per camera, threshold at 6 alerts
# Can be adjusted via WHATSAPP_COOLDOWN_SECONDS and WHATSAPP_ALERT_THRESHOLD env vars
_cooldown_seconds = float(os.getenv("WHATSAPP_COOLDOWN_SECONDS", "30"))
_alert_threshold = int(os.getenv("WHATSAPP_ALERT_THRESHOLD", "6"))
_whatsapp_cooldown = WhatsAppCooldownManager(
    cooldown_seconds=_cooldown_seconds,
    alert_threshold=_alert_threshold
)

# ============================================================================
# CONFIGURATION
# ============================================================================

def is_whatsapp_configured() -> bool:
    """
    Check if WhatsApp notifications are properly configured.
    
    Returns:
        True if either primary or fallback configuration is enabled and complete.
    """
    primary = _get_primary_config()
    fallback = _get_fallback_config()
    return _is_config_valid(primary) or _is_config_valid(fallback)


# ============================================================================
# MESSAGE FORMATTING
# ============================================================================

def format_alert_message(
    zone: str,
    event_type: str,
    confidence: float,
    camera_id: Optional[str] = None,
    priority: Optional[str] = None,
    timestamp: Optional[float] = None,
    extra_info: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Format an incident into a WhatsApp alert message with AI-powered summary.
    
    Args:
        zone: Detection zone (e.g., "Corridor", "School Ground")
        event_type: Type of event (e.g., "Fight", "Weapon Detected")
        confidence: Detection confidence (0.0 - 1.0)
        camera_id: Optional camera identifier
        priority: Optional priority level (critical, high, medium, low)
        timestamp: Optional Unix timestamp (uses current time if not provided)
        extra_info: Optional additional information
        snapshot_path: Optional path to snapshot image for AI analysis
        metadata: Optional event metadata for AI context
    
    Returns:
        Formatted WhatsApp message string with AI summary
    """
    # Format timestamp
    if timestamp:
        ts_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
    else:
        ts_str = datetime.now().strftime("%H:%M:%S")
    
    # Format event type for display
    event_display = event_type.replace("_", " ").title()
    
    # Build message
    lines = [
        "🚨 *SentinelAI Alert*",
        "",
        f"📍 Zone: {zone}",
        f"⚠️ Event: {event_display}",
        f"📊 Confidence: {confidence:.0%}",
        f"🕐 Time: {ts_str}",
    ]
    
    if camera_id:
        lines.append(f"📷 Camera: {camera_id}")
    
    if priority:
        priority_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
        }.get(priority.lower(), "⚪")
        lines.append(f"{priority_emoji} Priority: {priority.upper()}")
    
    # Generate AI summary if snapshot is available
    if snapshot_path:
        ai_summary = generate_ai_summary(
            zone=zone,
            event_type=event_type,
            confidence=confidence,
            snapshot_path=snapshot_path,
            metadata=metadata
        )
        if ai_summary:
            lines.append("")
            lines.append("🤖 *AI Analysis:*")
            lines.append(ai_summary)
    
    if extra_info:
        lines.append("")
        lines.append(f"📝 Info: {extra_info}")
    
    return "\n".join(lines)


def format_incident_message(incident: Dict[str, Any]) -> str:
    """
    Format an incident dictionary into a WhatsApp alert message.
    
    Args:
        incident: Incident dictionary from the event engine
    
    Returns:
        Formatted WhatsApp message string
    """
    event = incident.get("event", {})
    
    return format_alert_message(
        zone=event.get("zone", "Unknown"),
        event_type=event.get("event_type", "Unknown Event"),
        confidence=event.get("confidence", 0.0),
        camera_id=event.get("camera_id"),
        priority=incident.get("priority"),
        timestamp=event.get("timestamp"),
    )


# ============================================================================
# SEND FUNCTIONS
# ============================================================================

def _send_with_config(config: Dict[str, Any], message: str) -> bool:
    if not _is_config_valid(config):
        return False

    try:
        logger.info("=" * 80)
        logger.info(f"[WHATSAPP_SEND_START] Using {config['name']} Twilio account")
        logger.info(f"  From: {config['from_number']}")
        logger.info(f"  To: {config['to_number']}")
        logger.info("=" * 80)

        from twilio.rest import Client

        client = Client(config["account_sid"], config["auth_token"])

        if _is_valid_template_sid(config.get("template_sid", "")):
            logger.info(
                f"[TWILIO_REQUEST] Sending WhatsApp template message via {config['name']}"
            )
            twilio_message = client.messages.create(
                from_=config["from_number"],
                to=config["to_number"],
                content_sid=config["template_sid"],
                content_variables=json.dumps(config.get("template_vars", {})) if config.get("template_vars") else None,
            )
        else:
            logger.info(
                f"[TWILIO_REQUEST] Sending WhatsApp freeform message via {config['name']}"
            )
            twilio_message = client.messages.create(
                body=message,
                from_=config["from_number"],
                to=config["to_number"],
            )

        logger.info("=" * 80)
        logger.warning(
            f"✅ [WHATSAPP_SEND_SUCCESS] Message sent successfully! "
            f"SID: {twilio_message.sid} | "
            f"Status: {twilio_message.status} | "
            f"To: {config['to_number']}"
        )
        logger.info("=" * 80)
        return True

    except ImportError:
        logger.error(
            "❌ WhatsApp alert failed: Twilio SDK not installed. "
            "Run: pip install twilio"
        )
        return False

    except Exception as e:
        error_msg = str(e)
        if config.get("auth_token") and config["auth_token"] in error_msg:
            error_msg = error_msg.replace(config["auth_token"], "***")
        if config.get("account_sid") and config["account_sid"] in error_msg:
            error_msg = error_msg.replace(config["account_sid"], "***")

        logger.error("=" * 80)
        logger.error("❌ [WHATSAPP_SEND_FAILED] Error sending WhatsApp message:")
        logger.error(f"  Error: {error_msg}")
        logger.error(f"  To: {config.get('to_number')}")
        logger.error("=" * 80)
        return False


def send_whatsapp_alert(message: str) -> bool:
    """
    Send a WhatsApp alert message via Twilio (blocking).
    
    Args:
        message: The message text to send
    
    Returns:
        True if message was sent successfully, False otherwise
    
    Note:
        This is a blocking call. For non-blocking behavior, use
        send_whatsapp_alert_nonblocking() or send_whatsapp_alert_async().
    """
    primary = _get_primary_config()
    fallback = _get_fallback_config()

    if not _is_config_valid(primary) and not _is_config_valid(fallback):
        logger.debug(
            "WhatsApp alerts disabled or not configured. "
            "Set WHATSAPP_ALERTS_ENABLED/WHATSAPP_FALLBACK_ENABLED and credentials."
        )
        return False

    primary_result = _send_with_config(primary, message) if _is_config_valid(primary) else False
    if primary_result:
        return True

    if _is_config_valid(fallback):
        logger.warning("[WHATSAPP_FALLBACK] Primary send failed; trying fallback account.")
        return _send_with_config(fallback, message)

    return False


def send_whatsapp_alert_nonblocking(message: str, camera_id: Optional[str] = None) -> None:
    """
    Send a WhatsApp alert message in a background thread (non-blocking).
    
    This is the recommended method for use in the event pipeline to avoid
    blocking inference or request processing.
    
    Features:
    - Per-camera cooldown: Only ONE alert per camera within cooldown period (30s)
    - Alert threshold: After 6+ alerts, trigger 60s extended cooldown
    - Fire-and-forget: No return value
    - Failures are logged but do not propagate
    - Uses a thread pool to limit concurrent sends
    
    Args:
        message: The message text to send
        camera_id: Optional camera identifier for deduplication cooldown.
                   If provided, alerts from the same camera are throttled.
    
    Note:
        If camera_id is provided and cooldown is active for that camera,
        the alert will be skipped. This prevents duplicate alerts.
    """
    primary = _get_primary_config()
    fallback = _get_fallback_config()

    if not _is_config_valid(primary) and not _is_config_valid(fallback):
        logger.debug("WhatsApp not configured. Skipping alert.")
        return
    
    # Check per-camera cooldown to prevent duplicates
    if camera_id:
        if not _whatsapp_cooldown.should_send(camera_id):
            remaining = _whatsapp_cooldown.get_remaining_cooldown(camera_id)
            alert_count = _whatsapp_cooldown.get_alert_count(camera_id)
            is_threshold = _whatsapp_cooldown.is_threshold_active(camera_id)
            
            if is_threshold:
                logger.warning(
                    f"[WHATSAPP_BLOCKED] Camera={camera_id} | "
                    f"Alerts={alert_count}/{_alert_threshold} | "
                    f"EXTENDED COOLDOWN ACTIVE (next in {remaining:.1f}s)"
                )
            else:
                logger.info(
                    f"[WHATSAPP_COOLDOWN] Camera={camera_id} | "
                    f"Alerts={alert_count} | "
                    f"Skipping duplicate (next in {remaining:.1f}s)"
                )
            return
    
    def _send_wrapper():
        try:
            result = send_whatsapp_alert(message)
            if result:
                logger.warning(f"✅ [WHATSAPP_BACKGROUND_SENT] Message sent successfully from background thread")
            else:
                logger.error(f"❌ [WHATSAPP_BACKGROUND_FAILED] Message send returned False from background thread")
        except Exception as e:
            logger.error(f"❌ [WHATSAPP_BACKGROUND_ERROR] Unhandled exception in background send: {e}", exc_info=True)
    
    cam_info = f" (camera={camera_id})" if camera_id else ""
    alert_count = _whatsapp_cooldown.get_alert_count(camera_id) if camera_id else 0
    logger.warning(f"⏳ Queuing WhatsApp alert in background thread{cam_info} [Alert #{alert_count}]...")
    _executor.submit(_send_wrapper)


async def send_whatsapp_alert_async(message: str) -> bool:
    """
    Send a WhatsApp alert message asynchronously.
    
    For use in async contexts (FastAPI endpoints, async workers).
    
    Args:
        message: The message text to send
    
    Returns:
        True if message was sent successfully, False otherwise
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, send_whatsapp_alert, message)


# ============================================================================
# HIGH-LEVEL ALERT FUNCTIONS
# ============================================================================

def send_incident_alert(incident: Dict[str, Any], blocking: bool = False) -> Optional[bool]:
    """
    Send a WhatsApp alert for an incident.
    
    Args:
        incident: Incident dictionary from the event engine
        blocking: If True, wait for send to complete. If False (default), fire-and-forget.
    
    Returns:
        True/False if blocking=True, None if blocking=False
    """
    message = format_incident_message(incident)
    
    if blocking:
        return send_whatsapp_alert(message)
    else:
        send_whatsapp_alert_nonblocking(message)
        return None


def send_critical_alert(
    event_type: str,
    zone: str,
    confidence: float,
    camera_id: Optional[str] = None,
    blocking: bool = False,
) -> Optional[bool]:
    """
    Send a WhatsApp alert for a critical detection event.
    
    Convenience function for common alert scenarios.
    
    Args:
        event_type: Type of event detected
        zone: Detection zone
        confidence: Detection confidence
        camera_id: Optional camera ID
        blocking: If True, wait for send to complete
    
    Returns:
        True/False if blocking=True, None if blocking=False
    """
    message = format_alert_message(
        zone=zone,
        event_type=event_type,
        confidence=confidence,
        camera_id=camera_id,
        priority="critical",
    )
    
    if blocking:
        return send_whatsapp_alert(message)
    else:
        send_whatsapp_alert_nonblocking(message)
        return None


# ============================================================================
# TESTING / DEBUG
# ============================================================================

def test_whatsapp_connection() -> Dict[str, Any]:
    """
    Test the WhatsApp configuration and send a test message.
    
    Returns:
        Dict with status information
    """
    primary = _get_primary_config()
    fallback = _get_fallback_config()
    
    result = {
        "configured": is_whatsapp_configured(),
        "enabled": primary["enabled"],
        "has_account_sid": bool(primary["account_sid"]),
        "has_auth_token": bool(primary["auth_token"]),
        "has_to_number": bool(primary["to_number"]),
        "from_number": primary["from_number"],
        "fallback_enabled": fallback["enabled"],
        "fallback_has_account_sid": bool(fallback["account_sid"]),
        "fallback_has_auth_token": bool(fallback["auth_token"]),
        "fallback_has_to_number": bool(fallback["to_number"]),
        "fallback_from_number": fallback["from_number"],
        "test_sent": False,
        "error": None,
    }
    
    if not result["configured"]:
        result["error"] = "WhatsApp not fully configured"
        return result
    
    try:
        test_message = (
            "✅ *SentinelAI Test Alert*\n\n"
            "This is a test message from your SentinelAI system.\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "If you received this, WhatsApp alerts are working correctly!"
        )
        
        result["test_sent"] = send_whatsapp_alert(test_message)
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


if __name__ == "__main__":
    # Quick test when run directly
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("Testing WhatsApp configuration...")
    result = test_whatsapp_connection()
    
    print(f"\nConfiguration Status:")
    print(f"  Enabled: {result['enabled']}")
    print(f"  Configured: {result['configured']}")
    print(f"  Has Account SID: {result['has_account_sid']}")
    print(f"  Has Auth Token: {result['has_auth_token']}")
    print(f"  Has To Number: {result['has_to_number']}")
    print(f"  From Number: {result['from_number']}")
    
    if result['test_sent']:
        print("\n✅ Test message sent successfully!")
    elif result['error']:
        print(f"\n❌ Error: {result['error']}")
    else:
        print("\n⚠️ Test message not sent (check configuration)")
    
    sys.exit(0 if result['test_sent'] else 1)

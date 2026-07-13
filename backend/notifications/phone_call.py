"""
SentinelAI Phone Call Alert Module

Integrates with Twilio to make emergency phone calls when multiple
high-severity alerts are detected from the same camera.

Usage:
    from notifications.phone_call import trigger_call_alert
    
    # Trigger emergency call
    trigger_call_alert(
        "Emergency. Multiple high severity incidents detected on camera cam1. "
        "Please check dashboard immediately."
    )

Environment Variables Required:
    TWILIO_ACCOUNT_SID     - Twilio Account SID
    TWILIO_AUTH_TOKEN      - Twilio Auth Token
    TWILIO_PHONE_FROM      - Twilio phone number to call FROM (e.g., +13253082341)
    TWILIO_PHONE_TO        - Phone number to call TO (e.g., +919952079613)
    PHONE_ALERTS_ENABLED   - Set to 'true' to enable calls (default: false)
"""

import os
import logging
import threading
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# Initialize logger
logger = logging.getLogger(__name__)

# Thread pool for non-blocking calls
_call_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phone_call_")


# ============================================================================
# CONFIGURATION
# ============================================================================

def _get_call_config() -> Dict[str, Any]:
    """Get Twilio phone call configuration from environment variables."""
    return {
        "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "auth_token": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "from_number": os.getenv("TWILIO_PHONE_FROM", ""),
        "to_number": os.getenv("TWILIO_PHONE_TO", ""),
        "enabled": os.getenv("PHONE_ALERTS_ENABLED", "false").lower() in ("true", "1", "yes", "on"),
    }


def is_phone_configured() -> bool:
    """
    Check if phone call alerts are properly configured.
    
    Returns:
        True if all required environment variables are set and enabled.
    """
    config = _get_call_config()
    
    if not config["enabled"]:
        return False
    
    required = [config["account_sid"], config["auth_token"], config["from_number"], config["to_number"]]
    return all(required)


# ============================================================================
# PHONE CALL FUNCTIONS
# ============================================================================

def trigger_call_alert(message: str) -> bool:
    """
    Make an emergency phone call via Twilio (blocking).
    
    Uses TwiML to convert text to speech for the call.
    
    Args:
        message: The message to speak during the call
    
    Returns:
        True if call was initiated successfully, False otherwise
    """
    config = _get_call_config()
    
    # Check if enabled
    if not config["enabled"]:
        logger.debug("Phone alerts disabled. Set PHONE_ALERTS_ENABLED=true to enable.")
        return False
    
    # Validate configuration
    if not config["account_sid"] or not config["auth_token"]:
        logger.warning("Phone alert skipped: TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not configured.")
        return False
    
    if not config["from_number"]:
        logger.warning("Phone alert skipped: TWILIO_PHONE_FROM not configured.")
        return False
    
    if not config["to_number"]:
        logger.warning("Phone alert skipped: TWILIO_PHONE_TO not configured.")
        return False
    
    try:
        # Import Twilio client (lazy import to avoid startup errors if not installed)
        from twilio.rest import Client
        
        # Create Twilio client
        client = Client(config["account_sid"], config["auth_token"])
        
        # Build TwiML for text-to-speech
        # Repeat message twice for clarity
        twiml = f"""
        <Response>
            <Say voice="alice" language="en-US">
                {message}
            </Say>
            <Pause length="1"/>
            <Say voice="alice" language="en-US">
                I repeat: {message}
            </Say>
        </Response>
        """
        
        # Make the call
        call = client.calls.create(
            twiml=twiml,
            from_=config["from_number"],
            to=config["to_number"]
        )
        
        logger.warning(
            f"🚨 EMERGENCY PHONE CALL INITIATED! "
            f"SID: {call.sid}, "
            f"To: {config['to_number'][-4:].rjust(len(config['to_number']), '*')}, "
            f"Status: {call.status}"
        )
        return True
        
    except ImportError:
        logger.error(
            "Phone alert failed: Twilio SDK not installed. "
            "Run: pip install twilio"
        )
        return False
        
    except Exception as e:
        # Log error without exposing credentials
        error_msg = str(e)
        # Sanitize any potential credential leaks
        if config["auth_token"] and config["auth_token"] in error_msg:
            error_msg = error_msg.replace(config["auth_token"], "***")
        if config["account_sid"] and config["account_sid"] in error_msg:
            error_msg = error_msg.replace(config["account_sid"], "***")
        
        logger.error(f"Phone alert failed: {error_msg}")
        return False


def trigger_call_alert_nonblocking(message: str) -> None:
    """
    Make an emergency phone call in a background thread (non-blocking).
    
    Args:
        message: The message to speak during the call
    
    Note:
        - Fire-and-forget: No return value
        - Failures are logged but do not propagate
    """
    config = _get_call_config()
    
    # Quick check before spawning thread
    if not config["enabled"]:
        logger.debug("Phone alerts disabled. Skipping.")
        return
    
    if not all([config["account_sid"], config["auth_token"], config["from_number"], config["to_number"]]):
        logger.debug("Phone not configured. Skipping call.")
        return
    
    def _call_wrapper():
        try:
            trigger_call_alert(message)
        except Exception as e:
            logger.error(f"Phone call background send failed: {e}")
    
    logger.warning("🚨 Queuing EMERGENCY PHONE CALL in background thread...")
    _call_executor.submit(_call_wrapper)


# ============================================================================
# HIGH-ALERT COUNTER FOR MULTI-INCIDENT CALLS
# ============================================================================

class HighAlertCallTrigger:
    """
    Tracks high-confidence alerts per camera and triggers phone call
    when threshold is reached.
    
    When 3 high-confidence (>=0.85) alerts occur from the same camera,
    an emergency phone call is triggered automatically.
    """
    
    def __init__(self, threshold_count: int = 3, min_confidence: float = 0.85):
        """
        Args:
            threshold_count: Number of high alerts before triggering call
            min_confidence: Minimum confidence to count as high alert
        """
        self._threshold = threshold_count
        self._min_confidence = min_confidence
        self._camera_alert_counts: Dict[str, int] = {}
        self._lock = threading.Lock()
    
    def record_alert(self, camera_id: str, confidence: float) -> bool:
        """
        Record a high-confidence alert and check if call should be triggered.
        
        Args:
            camera_id: Camera identifier
            confidence: Event confidence score (0.0 - 1.0)
        
        Returns:
            True if phone call was triggered, False otherwise
        """
        # Only count high-confidence alerts
        if confidence < self._min_confidence:
            logger.debug(
                f"[CALL_TRIGGER] Skipping low-confidence alert: "
                f"camera={camera_id} confidence={confidence:.2f} (min={self._min_confidence})"
            )
            return False
        
        with self._lock:
            # Increment counter for this camera
            current_count = self._camera_alert_counts.get(camera_id, 0)
            current_count += 1
            self._camera_alert_counts[camera_id] = current_count
            
            logger.info(
                f"[CALL_TRIGGER] High alert recorded: camera={camera_id} "
                f"confidence={confidence:.2f} count={current_count}/{self._threshold}"
            )
            
            # Check if threshold reached
            if current_count >= self._threshold:
                # Reset counter for this camera
                self._camera_alert_counts[camera_id] = 0
                
                # Trigger emergency call
                message = (
                    f"Emergency. Multiple high severity incidents detected on camera {camera_id}. "
                    f"Please check dashboard immediately."
                )
                
                logger.warning(
                    f"🚨 [CALL_TRIGGER] THRESHOLD REACHED! "
                    f"camera={camera_id} count={current_count} - Triggering emergency call!"
                )
                
                # Non-blocking call
                trigger_call_alert_nonblocking(message)
                return True
            
            return False
    
    def get_count(self, camera_id: str) -> int:
        """Get current alert count for a camera."""
        with self._lock:
            return self._camera_alert_counts.get(camera_id, 0)
    
    def reset_camera(self, camera_id: str) -> None:
        """Reset counter for a specific camera."""
        with self._lock:
            self._camera_alert_counts.pop(camera_id, None)
    
    def reset_all(self) -> None:
        """Reset all camera counters."""
        with self._lock:
            self._camera_alert_counts.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get all camera alert counts."""
        with self._lock:
            return dict(self._camera_alert_counts)


# Global instance - triggers call after 3 high-confidence alerts per camera
_high_alert_trigger = HighAlertCallTrigger(threshold_count=3, min_confidence=0.85)


def record_high_alert(camera_id: str, confidence: float) -> bool:
    """
    Record a high-confidence alert. If 3 alerts from same camera, triggers call.
    
    Args:
        camera_id: Camera identifier
        confidence: Event confidence score
    
    Returns:
        True if phone call was triggered
    """
    return _high_alert_trigger.record_alert(camera_id, confidence)


def get_alert_stats() -> Dict[str, int]:
    """Get current alert counts for all cameras."""
    return _high_alert_trigger.get_stats()

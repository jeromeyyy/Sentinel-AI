import os
import time
import logging
from typing import Dict, List
from pathlib import Path

import requests

# Import WhatsApp notification module
try:
    from notifications.whatsapp import (
        send_whatsapp_alert_nonblocking,
        format_alert_message,
        is_whatsapp_configured,
    )
    WHATSAPP_AVAILABLE = True
except ImportError:
    WHATSAPP_AVAILABLE = False

# Import Phone Call notification module (emergency escalation)
try:
    from notifications.phone_call import (
        record_high_alert,
        is_phone_configured,
    )
    PHONE_CALL_AVAILABLE = True
except ImportError:
    PHONE_CALL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Get backend URL for constructing public snapshot URLs
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").replace("/event", "")

# Log module availability
if WHATSAPP_AVAILABLE:
    logger.info("✅ WhatsApp notification module loaded successfully")
else:
    logger.warning("⚠️ WhatsApp notification module not available")

if PHONE_CALL_AVAILABLE:
    logger.info("✅ Phone call notification module loaded successfully")
else:
    logger.warning("⚠️ Phone call notification module not available")

"""
Alert service for SAAS school module.

This stays transport‑agnostic: instead of actually calling SMS /
WhatsApp / ambulances / fire brigade, it returns a rich `alert`
payload listing *what* would be done so the caller (or another
worker) can integrate with real services later.

WhatsApp Integration:
When an incident crosses the suspicion threshold, a WhatsApp alert
is sent via Twilio Sandbox (non-blocking).
"""


def _base_summary(incident: Dict) -> str:
    event = incident.get("event", {})
    event_type = event.get("event_type", "unknown")
    confidence = event.get("confidence", 0.0)
    priority = incident.get("priority", "medium")
    return (
        f"{event_type.replace('_', ' ').title()} detected "
        f"(priority: {priority}, confidence: {confidence:.2f})."
    )


def _scenario_actions(incident: Dict) -> Dict:
    """
    Map the engine playbook into concrete, human-readable actions.
    """
    playbook = incident.get("playbook", {}) or {}
    event = incident.get("event", {}) or {}
    event_type = event.get("event_type")

    actions: List[str] = []
    evidence: Dict = {}
    notifications: Dict = {}
    automations: Dict = {}

    # Common context
    camera_id = event.get("camera_id")
    tenant_id = event.get("tenant_id")
    event_id = event.get("event_id")
    ts = event.get("timestamp", time.time())

    # Snapshot / clip references are symbolic; real system would
    # actually cut frames/segments and persist to storage.
    snapshot_ref = f"snapshot://{tenant_id}/{camera_id}/{event_id}"
    clip_ref = f"clip://{tenant_id}/{camera_id}/{event_id}"

    if playbook.get("include_snapshot"):
        evidence["snapshot_ref"] = snapshot_ref
        actions.append("Captured and stored snapshot of incident frame.")

    if playbook.get("flag_timestamped_clips"):
        evidence["clip_ref"] = clip_ref
        evidence["locked"] = playbook.get("lock_clip_in_evidence_store", False)
        actions.append("Flagged timestamped video clip in evidence store.")

    # Scenario‑specific logic
    scenario = playbook.get("scenario") or event_type

    if scenario == "fight_violence_crowd":
        notifications["security_app"] = {
            "priority": "high",
            "target_role": "nearest_security_or_duty_staff",
        }
        automations["live_view"] = {
            "camera_id": camera_id,
            "action": "open_live_stream_in_client",
        }
        actions.extend(
            [
                "Raised high-priority alert to duty/security app.",
                "Pushed live camera link to nearest staff.",
                "Marked incident timeline for later review.",
            ]
        )

    elif scenario == "exam_malpractice":
        notifications["invigilator"] = {
            "channel": "app",
            "priority": "medium",
        }
        actions.extend(
            [
                "Notified invigilator with snapshot and context.",
                "Locked flagged clip as exam malpractice evidence.",
            ]
        )

    elif scenario == "gate_accident":
        automations["emergency_workflow"] = {
            "type": "ambulance",
            "status": "requested",
        }
        notifications["security_admin"] = {
            "priority": "critical",
            "include_location": True,
            "camera_id": camera_id,
        }
        actions.extend(
            [
                "Triggered ambulance / emergency workflow.",
                "Notified security and admin with camera + location.",
            ]
        )

    elif scenario == "unauthorized_entry":
        notifications["security"] = {"priority": "high"}
        automations["gates"] = {
            "action": "lock_if_integrated",
            "camera_id": camera_id,
        }
        automations["recording"] = {
            "mode": "high_fidelity",
            "started_at": ts,
        }
        actions.extend(
            [
                "Notified security about after-hours intrusion.",
                "Requested gate lock (if integrated).",
                "Started high-fidelity recording around incident.",
            ]
        )

    elif scenario == "abandoned_object":
        automations["reid_probe"] = {
            "action": "identify_subject_who_left_object",
            "clip_ref": clip_ref,
        }
        automations["zone_lockdown"] = {
            "mode": "conditional",
            "trigger": "high_risk_assessment",
        }
        actions.extend(
            [
                "Raised timestamped alert for abandoned object.",
                "Launched ReID probe to find who left the object.",
                "Prepared auto zone lockdown if object is high-risk.",
            ]
        )

    elif scenario == "fire_smoke":
        automations["fire_service"] = {
            "type": "fire",
            "status": "requested",
        }
        notifications["emergency_panel"] = {
            "priority": "critical",
            "include_evac_map": True,
        }
        actions.extend(
            [
                "Raised immediate emergency notification for fire/smoke.",
                "Triggered fire service workflow (if configured).",
                "Displayed evacuation map and muster point guidance.",
            ]
        )

    return {
        "actions": actions,
        "evidence": evidence,
        "notifications": notifications,
        "automations": automations,
    }


def _build_llm_prompt(incident: Dict, scenario_block: Dict, summary: str) -> str:
    event = incident.get("event", {}) or {}
    playbook = incident.get("playbook", {}) or {}

    return (
        "You are an AI safety assistant for a school campus. "
        "Explain to a human operator what was detected on the camera, "
        "why it matters, and what actions the system is taking. "
        "Be concise (3–6 sentences) and non-technical.\n\n"
        f"High-level summary: {summary}\n\n"
        f"Event payload: {event}\n\n"
        f"Configured playbook: {playbook}\n\n"
        f"Derived actions: {scenario_block.get('actions', [])}\n"
    )


def _call_llm(prompt: str) -> str:
    """
    Call a free / OpenAI-compatible LLM endpoint if configured.

    Environment variables:
      - LLM_API_BASE: e.g. https://api.groq.com/openai, https://api.openai.com
      - LLM_API_KEY: API key for the provider
      - LLM_MODEL:   model name (provider-specific)

    If not configured or if the call fails, we fall back to a local,
    deterministic explanation string.
    """
    api_base = os.getenv("LLM_API_BASE")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_base or not api_key:
        return (
            "Automatically generated explanation based on recent frames and "
            "configured safety playbooks. (LLM endpoint is not configured, "
            "so this is a local fallback string.)"
        )

    try:
        url = api_base.rstrip("/") + "/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant helping school security staff "
                        "understand incidents detected on CCTV cameras."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
            or "LLM did not return an explanation."
        )
    except Exception:
        return (
            "Automatically generated explanation based on recent frames and "
            "configured safety playbooks. (LLM call failed; using fallback.)"
        )


def trigger_alert(incident: Dict) -> Dict:
    """
    Translate an incident from the engine into a concrete alert description.
    
    Also sends WhatsApp notification for high-priority incidents (non-blocking).
    """
    if not incident:
        return {"alert": False, "summary": "No incident data."}

    scenario_block = _scenario_actions(incident)
    summary = _base_summary(incident)

    # Real LLM explanation if configured, otherwise clean fallback.
    prompt = _build_llm_prompt(incident, scenario_block, summary)
    llm_explanation = _call_llm(prompt)

    alert = {
        "alert": True,
        "summary": summary,
        "llm_explanation": llm_explanation,
        "priority": incident.get("priority", "medium"),
        "suspicion_score": incident.get("suspicion_score"),
        "timeline": incident.get("timeline", {}),
        "event": incident.get("event", {}),
        **scenario_block,
    }

    # ─── WhatsApp Notification (Non-Blocking) ────────────────────────────────
    # Send WhatsApp alert for incidents that crossed the threshold
    _send_whatsapp_notification(incident, alert)

    # ─── Phone Call Escalation ───────────────────────────────────────────────
    # Track high-confidence alerts - triggers call after 3 from same camera
    _check_phone_call_escalation(incident)

    print(f"ALERT: {alert}")
    return alert


def _send_whatsapp_notification(incident: Dict, alert: Dict) -> None:
    """
    Send WhatsApp notification for an incident (non-blocking).
    
    Only sends for certain priority levels and event types.
    Failures are logged but do not affect the main alert flow.
    """
    if not WHATSAPP_AVAILABLE:
        logger.debug("WhatsApp module not available, skipping notification.")
        return
    
    if not is_whatsapp_configured():
        logger.debug("WhatsApp not configured, skipping notification.")
        return
    
    try:
        event = incident.get("event", {})
        priority = incident.get("priority", "medium")
        event_type = event.get("event_type", "unknown")
        
        # Define which events should trigger WhatsApp alerts
        # Critical and high priority events always get WhatsApp alerts
        # All detected security events should be notified
        whatsapp_event_types = {
            "weapon_detected",
            "fight",
            "fire_smoke",
            "gate_accident",
            "intrusion",
            "fire_smoke_detected",
            "fall_detected",
            "crowd_formation",
            "mobile_usage",
            "after_hours_intrusion",
            "vehicle_detected",  # informational
        }
        
        should_send = (
            priority in ("critical", "high") or
            event_type in whatsapp_event_types
        )
        
        if not should_send:
            logger.debug(f"Skipping WhatsApp for low-priority event: {event_type}")
            return
        
        # Format the message with AI-powered summary
        zone = event.get("zone") or event.get("camera_zone", "Unknown Zone")
        confidence = event.get("confidence", 0.0)
        camera_id = event.get("camera_id", "unknown")
        timestamp = event.get("timestamp", time.time())
        snapshot_path = event.get("snapshot_path")
        metadata = event.get("metadata", {})
        
        message = format_alert_message(
            zone=zone,
            event_type=event_type,
            confidence=confidence,
            camera_id=camera_id,
            priority=priority,
            timestamp=timestamp,
            snapshot_path=snapshot_path,
            metadata=metadata,
        )
        
        # Send non-blocking (fire-and-forget) with camera_id for deduplication
        # Only one alert per camera within cooldown period (default 30s)
        logger.info(f"Triggering WhatsApp alert for {event_type} (priority: {priority}, camera={camera_id})")
        send_whatsapp_alert_nonblocking(message, camera_id=camera_id)
        
    except Exception as e:
        # Log but don't propagate - WhatsApp failure should not affect core functionality
        logger.error(f"Failed to send WhatsApp notification: {e}")


def _check_phone_call_escalation(incident: Dict) -> None:
    """
    Check if phone call should be triggered based on high-confidence alerts.
    
    When 3 high-confidence (>=0.85) alerts occur from the same camera,
    an emergency phone call is automatically triggered.
    
    Failures are logged but do not affect the main alert flow.
    """
    if not PHONE_CALL_AVAILABLE:
        logger.debug("Phone call module not available, skipping escalation check.")
        return
    
    if not is_phone_configured():
        logger.debug("Phone calls not configured, skipping escalation check.")
        return
    
    try:
        event = incident.get("event", {})
        camera_id = event.get("camera_id", "unknown")
        confidence = event.get("confidence", 0.0)
        
        # Record the high alert - this will trigger call if threshold reached
        call_triggered = record_high_alert(camera_id, confidence)
        
        if call_triggered:
            logger.warning(
                f"🚨 EMERGENCY CALL TRIGGERED for camera={camera_id} "
                f"(3+ high-confidence alerts detected)"
            )
        
    except Exception as e:
        # Log but don't propagate - phone call failure should not affect core functionality
        logger.error(f"Failed to check phone call escalation: {e}")

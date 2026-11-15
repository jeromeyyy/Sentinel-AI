# WhatsApp Alerts Configuration & Cooldown System

## Overview

SentinelAI includes a sophisticated WhatsApp alert system powered by **Twilio WhatsApp Sandbox**. The system prevents alert flooding with:

- **One alert per camera** within a 30-second window
- **Extended cooldown** after 6+ alerts (60 seconds) to prevent spam
- **Non-blocking sends** using thread pool architecture
- **Automatic deduplication** based on camera_id

## Configuration

### 1. Set Environment Variables in `.env`

```dotenv
# ── Twilio WhatsApp Notifications ───────────────────────────────────────
# Get credentials from: https://console.twilio.com
# For Sandbox: https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
TWILIO_ACCOUNT_SID=YOUR_ACCOUNT_SID
TWILIO_AUTH_TOKEN=YOUR_AUTH_TOKEN
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_TO=whatsapp:+919952079613
WHATSAPP_ALERTS_ENABLED=true

# Cooldown in seconds between alerts for the same camera (prevents duplicates)
# ONE alert per camera within this cooldown period
WHATSAPP_COOLDOWN_SECONDS=30

# Alert threshold: Trigger cooldown after 6+ alerts from same camera
# More than 6 alerts = trigger cooldown window to prevent spam
WHATSAPP_ALERT_THRESHOLD=6
```

### 2. Get Twilio Credentials

1. Go to [Twilio Console](https://console.twilio.com)
2. Sign in or create an account
3. Go to **Messaging > Try it Out > WhatsApp Learn**
4. Copy your credentials:
   - `ACCOUNT_SID`
   - `AUTH_TOKEN`
   - `FROM_NUMBER` (Twilio sandbox number, usually +1415-523-8886)

5. To receive messages, **register your phone number** in the Twilio WhatsApp Sandbox:
   - In the Sandbox settings, you'll see a registration message
   - Send that message from your phone number to register
   - Then set `TWILIO_WHATSAPP_TO` to your registered number

## Alert System Architecture

### Two-Tier Cooldown System

```
┌─────────────────────────────────────────────────────────────────┐
│              WhatsApp Alert Decision Tree                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Event Detected → Check: Is WhatsApp configured?               │
│                     ↓                                           │
│                   YES → Check: Camera cooldown active?         │
│                     ↓                                           │
│                   NO → Check: Alert count >= 6?               │
│                     ↓                                           │
│                   NO → Send alert + increment counter          │
│                          Mark timestamp for this camera        │
│                     ↓                                           │
│                   ✅ ALERT SENT                                │
│                                                                 │
│  ─────────────────────────────────────────────────────────────│
│  If cooldown is active:                                        │
│                     ↓                                           │
│                   YES → Skip alert (log: duplicate prevention) │
│                          Check remaining cooldown              │
│                     ↓                                           │
│                   ❌ ALERT BLOCKED (logged as skipped)         │
│                                                                 │
│  ─────────────────────────────────────────────────────────────│
│  If alert count >= threshold (6):                              │
│                     ↓                                           │
│                   YES → Activate extended cooldown (60s)       │
│                          Log warning about threshold reached   │
│                          Next alert only after 60s             │
│                     ↓                                           │
│                   ❌ EXTENDED COOLDOWN ACTIVE                  │
└─────────────────────────────────────────────────────────────────┘
```

### Alert Flow

1. **Event Detection** → `engine.py` processes video frame
2. **Incident Generated** → `service.py` calls `trigger_alert()`
3. **WhatsApp Notification** → `_send_whatsapp_notification()` checks cooldown
4. **Camera Filter** → If camera_id provided, check `_whatsapp_cooldown.should_send()`
5. **Decision** → 
   - ✅ Send: If within cooldown window AND under 6 alerts
   - ⏸️ Skip: If in normal cooldown (30s) → Log "duplicate prevention"
   - 🚫 Block: If in extended cooldown (60s) → Log "threshold reached"
6. **Background Send** → `send_whatsapp_alert_nonblocking()` queues in thread pool
7. **Twilio API** → Send via `twilio.rest.Client`
8. **Delivery** → Message arrives on registered phone number

## Alert Counters & Thresholds

### System Tracks Per Camera:

| Metric | Value | Purpose |
|--------|-------|---------|
| Alert Count | 0-N | Tracks how many alerts sent in current window |
| Last Alert Time | Unix timestamp | Used to calculate remaining cooldown |
| Cooldown Duration | 30s (default) | Minimum time between alerts |
| Alert Threshold | 6 (default) | Triggers extended cooldown |
| Extended Cooldown | 60s (2x normal) | Active when threshold reached |

### Example Timeline:

```
Time 0s:   Alert #1 → ✅ SENT (cam1)
Time 5s:   Alert #2 → ✅ SENT (cam1)
Time 10s:  Alert #3 → ✅ SENT (cam1)
Time 20s:  Alert #4 → ✅ SENT (cam1)
Time 25s:  Alert #5 → ✅ SENT (cam1)
Time 28s:  Alert #6 → ✅ SENT (cam1)
           ⚠️ Threshold reached! Extended cooldown active (60s)

Time 32s:  Alert #7 → ⏸️ BLOCKED (still in 60s extended cooldown)
           Last sent: 4s ago, cooldown expires: 28s

Time 95s:  Alert #8 → ✅ SENT (extended cooldown expired)
           Counter resets, normal cooldown resumes
```

## Testing Alert System

### 1. Check WhatsApp Configuration

```bash
curl http://localhost:8000/api/debug/whatsapp/status
```

**Response:**
```json
{
  "whatsapp_available": true,
  "enabled": true,
  "configured": true,
  "has_account_sid": true,
  "has_auth_token": true,
  "has_to_number": true,
  "from_number": "whatsapp:+14155238886"
}
```

### 2. Send Test WhatsApp Alert

```bash
# Send test alert for camera "cam1"
curl http://localhost:8000/api/debug/whatsapp/test-alert/cam1

# Send test alert for camera "cam2"
curl http://localhost:8000/api/debug/whatsapp/test-alert/cam2
```

**Response:**
```json
{
  "success": true,
  "message": "Test alert queued for sending",
  "camera_id": "cam1",
  "alert_count": 1,
  "cooldown_active": false,
  "threshold_active": false,
  "remaining_cooldown_seconds": 0,
  "next_alert_allowed_in": 0
}
```

### 3. Test Cooldown (Rapid Fires)

```bash
# Send 8 alerts rapidly (will be rate-limited)
for i in {1..8}; do
  echo "Alert $i"
  curl http://localhost:8000/api/debug/whatsapp/test-alert/cam1
  sleep 2
done
```

**Expected Behavior:**
- Alerts 1-6: ✅ SENT
- Alert 6: Threshold triggered → Extended cooldown begins
- Alerts 7-8: ⏸️ BLOCKED (in extended cooldown)
- After 60s: Cooldown expires, counter resets

### 4. Test Multiple Cameras (No Interference)

```bash
# Camera 1 gets alerts
curl http://localhost:8000/api/debug/whatsapp/test-alert/cam1
curl http://localhost:8000/api/debug/whatsapp/test-alert/cam1  # Blocked (cooldown)

# Camera 2 independent
curl http://localhost:8000/api/debug/whatsapp/test-alert/cam2  # ✅ Sent (different camera)
```

## Log Messages

### Successful Send
```
INFO | Queuing WhatsApp alert in background thread (camera=cam1) [Alert #1]...
INFO | WhatsApp alert sent successfully. SID: SM12345..., To: ****9613
```

### Duplicate Prevention
```
INFO | [WHATSAPP_COOLDOWN] Camera=cam1 | Alerts=2 | Skipping duplicate (next in 28.5s)
```

### Threshold Reached
```
WARNING | [WHATSAPP_THRESHOLD] Camera cam1 has reached 6 alerts. Activating extended cooldown (60s).
WARNING | [WHATSAPP_BLOCKED] Camera=cam1 | Alerts=6/6 | EXTENDED COOLDOWN ACTIVE (next in 55.2s)
```

### Configuration Issues
```
WARNING | WhatsApp alert skipped: TWILIO_WHATSAPP_TO not configured.
DEBUG | WhatsApp alerts disabled. Set WHATSAPP_ALERTS_ENABLED=true to enable.
ERROR | WhatsApp alert failed: Twilio SDK not installed. Run: pip install twilio
```

## Troubleshooting

### Problem: "WhatsApp not configured" error

**Solution:**
1. Verify `.env` file has all required variables
2. Check ACCOUNT_SID and AUTH_TOKEN are correct
3. Ensure WHATSAPP_ALERTS_ENABLED=true
4. Verify phone number is registered in Twilio sandbox

```bash
# Test configuration
curl http://localhost:8000/api/debug/whatsapp/status
```

### Problem: Messages not arriving on phone

**Solution:**
1. Verify phone number is registered in Twilio WhatsApp Sandbox
2. Check Twilio Dashboard for failed messages
3. Confirm `TWILIO_WHATSAPP_TO` matches registered number
4. Try sending test message from Twilio console directly

### Problem: Getting blocked/rate-limited

**Solution:**
- This is **normal behavior** - the system is preventing spam
- Check logs for cooldown messages
- Wait for cooldown to expire:
  - Normal: 30 seconds (COOLDOWN_SECONDS)
  - Extended: 60 seconds (after 6 alerts)

### Problem: Twilio SDK not installed

**Solution:**
```bash
$ pip install twilio
$ # Restart backend
$ cd backend && uvicorn main:app --reload
```

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `WHATSAPP_ALERTS_ENABLED` | false | Enable/disable WhatsApp alerts |
| `WHATSAPP_COOLDOWN_SECONDS` | 30 | Minimum seconds between alerts per camera |
| `WHATSAPP_ALERT_THRESHOLD` | 6 | Number of alerts before extended cooldown |
| `TWILIO_COOLDOWN_MULTIPLIER` | 2 | Extended cooldown = cooldown * multiplier |

## Production Checklist

- [ ] Replace Twilio WhatsApp Sandbox with Production Account
- [ ] Update credentials in `.env` with production values
- [ ] Test with actual WhatsApp number (not sandbox registration)
- [ ] Configure alert levels for production (consider increasing threshold)
- [ ] Monitor Twilio billing for SMS/WhatsApp costs
- [ ] Set up Twilio webhooks for delivery/read status
- [ ] Review alert frequency based on your use case
- [ ] Document escalation procedures for alerts

## API Reference

### Test Configuration
```
GET /api/debug/whatsapp/status
```

### Send Test Alert
```
GET /api/debug/whatsapp/test-alert/{camera_id}

Query Parameters:
  - camera_id: Camera identifier for deduplication (default: cam1)

Response:
{
  "success": boolean,
  "message": string,
  "camera_id": string,
  "alert_count": number,
  "cooldown_active": boolean,
  "threshold_active": boolean,
  "remaining_cooldown_seconds": number
}
```

### Test Connection
```
GET /api/debug/whatsapp/test
```

## Support

- Twilio Documentation: https://www.twilio.com/docs/whatsapp
- Twilio WhatsApp Sandbox: https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
- SentinelAI Issues: Check project GitHub repository

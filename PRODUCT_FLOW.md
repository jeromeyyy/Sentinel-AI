# SentinelAI - Complete Product Flow

## Current Implementation Status

### ✅ **Implemented Features**
- Landing/Config page with module selection
- Camera CRUD operations
- Live monitoring dashboard with camera grid
- Real-time alerts via WebSocket
- Incident timeline with filtering
- Analytics dashboard with charts
- Theme system (light/dark)
- Toast notifications
- Auto-reconnecting WebSocket
- Alert deduplication
- Camera health indicators
- MJPEG video streaming

### 🔨 **In Progress / Planned**
- Google OAuth integration
- Multi-tenant system
- Setup Wizard (step-based camera onboarding)
- Settings page
- Redis for worker coordination
- Database integration

---

## Complete Application Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER JOURNEY                            │
└─────────────────────────────────────────────────────────────────┘

1. LANDING / AUTHENTICATION
   ↓
   User visits app → Landing Page
   ↓
   [PLANNED] → Google OAuth Login
   ↓
   [PLANNED] → Tenant/Organization Creation
   ↓
   → Module Selection (Home/School/Office)
   ✅ Currently: Direct module selection on landing page

2. SETUP / ONBOARDING
   ↓
   → CCTV Setup Wizard [PLANNED]
      - Step 1: Camera Name & RTSP URL
      - Step 2: Zone Assignment
      - Step 3: Stream Preview & Test
      - Step 4: Confirm & Save
   ↓
   → Backend Camera Registration
   ✅ Currently: Modal form on landing page

3. CAMERA ACTIVATION
   ↓
   → Camera Config Saved to Backend
   ✅ POST /api/camera
   ↓
   → AI Worker Auto-Binds to Camera
   ✅ Worker polls /api/cameras, processes by zone
   ↓
   → Zone Model Assigned (corridor → yolov8n.pt, etc.)
   ✅ Implemented in worker.py

4. DETECTION PIPELINE
   ↓
   → RTSP/Video Stream Opened
   ✅ cv2.VideoCapture in worker
   ↓
   → YOLOv8 Detection + Tracking
   ✅ YOLO models + DeepSORT tracker
   ↓
   → Behavior Analysis (crowd, fight, weapon, etc.)
   ✅ Zone-specific detectors in ai_worker/zones/
   ↓
   → Event Engine Evaluates Threat
   ✅ event_engine/engine.py
   ↓
   → Alert Generated (if incident)
   ✅ alert_service/service.py

5. ALERT DELIVERY
   ↓
   → Event Posted to Backend
   ✅ POST /event
   ↓
   → WebSocket Broadcast to Clients
   ✅ WS /ws/alerts
   ↓
   → Frontend Receives Alert
   ✅ useWebSocket hook with auto-reconnect
   ↓
   → Alert Popup Displayed
   ✅ AlertPopupNew component with priority styling

6. MONITORING & ANALYTICS
   ↓
   → Live Dashboard View
   ✅ /monitor?tab=monitoring
      - Camera grid with MJPEG streams
      - Real-time alert panel
      - Active stats (cameras, incidents)
   ↓
   → Incident Timeline
   ✅ /monitor?tab=incidents
      - Filter by zone/type/priority
      - Search functionality
      - Pagination
      - Export to PDF
   ↓
   → Analytics Dashboard
   ✅ /monitor?tab=analytics
      - Bar chart: Incidents by type
      - Pie chart: Incidents by zone
      - Area chart: 7-day trend
      - Priority distribution
   ↓
   → Settings & Management
   [PLANNED] /monitor?tab=settings
      - Module change
      - Camera management
      - Worker status
      - System health
```

---

## API Flow Diagram

```
┌──────────────┐
│   Frontend   │ (Next.js 14, React 18)
└──────┬───────┘
       │
       │ HTTP REST
       ├─────────────► GET  /api/cameras
       ├─────────────► POST /api/camera
       ├─────────────► GET  /api/stats
       ├─────────────► GET  /incidents
       ├─────────────► GET  /api/analytics
       ├─────────────► GET  /video/{camera_id}  (MJPEG)
       ├─────────────► GET  /api/camera/{id}/health
       ├─────────────► GET  /api/system/health
       │
       │ WebSocket
       └─────────────► WS   /ws/alerts
                            │
                            ├─► alert events
                            ├─► incident updates
                            └─► heartbeat

┌──────────────┐
│   Backend    │ (FastAPI, Python 3.10+)
└──────┬───────┘
       │
       │ In-Memory State:
       │ - camera_configs: Dict
       │ - incidents: Dict
       │ - alerts_history: List
       │ - active_alert_clients: List[WebSocket]
       │
       │ [PLANNED] Redis:
       │ - camera:* (camera configs)
       │ - worker:* (worker status)
       │ - incident:* (incident data)
       │
       │ Receives Events:
       ◄───────────── POST /event (from AI Worker)
                      {
                        "camera_id": "cam_001",
                        "zone": "corridor",
                        "event_type": "fight_detected",
                        "timestamp": 1708289234.56,
                        "frame_url": "...",
                        "metadata": {...}
                      }

┌──────────────┐
│  AI Worker   │ (YOLOv8 + Tracker)
└──────┬───────┘
       │
       │ 1. Polls Backend for Cameras
       │    GET /api/cameras
       │
       │ 2. Opens Video Stream
       │    cv2.VideoCapture(rtsp_url)
       │
       │ 3. Detection Pipeline:
       │    - YOLOv8 object detection
       │    - DeepSORT tracking
       │    - Zone-specific behavior analysis
       │    - Event engine evaluation
       │
       │ 4. Posts Events to Backend
       │    POST /event
       │
       └─► Runs continuously per camera/zone
```

---

## WebSocket Event Structure

### Alert Event (Broadcast to Clients)
```json
{
  "type": "alert",
  "event": {
    "camera_id": "cam_corridor_01",
    "zone": "corridor",
    "event_type": "fight_detected",
    "timestamp": 1708289234.56,
    "frame_url": "/frames/incident_12345.jpg",
    "metadata": {
      "person_count": 3,
      "confidence": 0.87
    }
  },
  "alert": {
    "priority": "critical",
    "summary": "Physical altercation detected in corridor",
    "llm_explanation": "Multiple individuals engaged in aggressive behavior...",
    "recommended_action": "Dispatch security immediately"
  },
  "incident": {
    "id": "inc_12345",
    "resolved": false,
    "created_at": 1708289234.56
  }
}
```

---

## Data Persistence Strategy

### Current: In-Memory (Development)
```python
# backend/main.py
camera_configs: Dict[str, Dict] = {}
incidents: Dict[str, Dict] = {}
alerts_history: List[Dict] = []
```

### Planned: JSON File (Interim)
```
data/
  ├── tenants/
  │   ├── tenant_123.json
  │   └── tenant_456.json
  ├── cameras/
  │   ├── cam_001.json
  │   └── cam_002.json
  └── incidents/
      ├── 2026-02/
      │   ├── inc_001.json
      │   └── inc_002.json
```

### Future: PostgreSQL + Redis
```
PostgreSQL:
  - tenants (id, name, module, created_at)
  - cameras (id, tenant_id, name, rtsp_url, zone)
  - incidents (id, camera_id, event_type, timestamp, metadata)
  - users (id, email, tenant_id, role)

Redis:
  - camera:{id}:status (health check)
  - worker:{id}:heartbeat (worker alive)
  - alerts:queue (real-time alert queue)
```

---

## Compatibility Guarantees

### ✅ **No Breaking Changes**
- All existing REST endpoints remain unchanged
- WebSocket `/ws/alerts` event structure preserved
- Camera CRUD payloads stay the same
- Frontend components remain compatible
- Worker event posting format unchanged

### 🎯 **Backward Compatible Additions**
- New fields added as optional
- New endpoints added without removing old ones
- Multi-tenant support added as a layer, not replacement
- JSON file storage as fallback to in-memory

---

## Next Steps

1. **Google OAuth Integration** → `/pages/login.js`
2. **Tenant Management** → Backend tenant endpoints
3. **Setup Wizard** → `/pages/setup.js` (step-based UI)
4. **Settings Page** → `/pages/monitor.js?tab=settings`
5. **Multi-Tenant JSON Structure** → `data/tenants/*.json`
6. **Redis Worker Coordination** → Optional, maintains in-memory fallback

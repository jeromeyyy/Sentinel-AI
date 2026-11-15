# SentinelAI - System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                 │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Next.js Frontend (React 18, Tailwind CSS)                   │  │
│  │                                                               │  │
│  │  Pages:                                                       │  │
│  │  - Landing/Config (Module Selection)                         │  │
│  │  - Setup Wizard [PLANNED]                                    │  │
│  │  - Monitoring Dashboard (Camera Grid + Alerts)               │  │
│  │  - Incident Timeline (Filter + Search + Export)              │  │
│  │  - Analytics (Charts + Stats)                                │  │
│  │  - Settings [PLANNED]                                        │  │
│  │                                                               │  │
│  │  Components:                                                  │  │
│  │  - Layout (Sidebar + TopBar)                                 │  │
│  │  - UI Kit (Card, Badge, Button, Modal, etc.)                 │  │
│  │  - Alert Popups (Priority styled)                            │  │
│  │  - Camera Feed (MJPEG streaming)                             │  │
│  │                                                               │  │
│  │  Hooks:                                                       │  │
│  │  - useWebSocket (auto-reconnect, deduplication)              │  │
│  │  - useTheme (light/dark mode)                                │  │
│  │  - useToast (notifications)                                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│         │                          │                                │
│         │ HTTP REST                │ WebSocket                      │
│         ▼                          ▼                                │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                               │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  FastAPI Backend (Python 3.10+)                              │  │
│  │                                                               │  │
│  │  REST Endpoints:                                              │  │
│  │  ├─ /api/cameras            → Camera CRUD                    │  │
│  │  ├─ /api/camera/{id}        → Single camera ops              │  │
│  │  ├─ /api/camera/{id}/health → Camera health check            │  │
│  │  ├─ /api/stats              → System statistics              │  │
│  │  ├─ /api/system/health      → Overall system health          │  │
│  │  ├─ /incidents              → Incident list                  │  │
│  │  ├─ /api/analytics          → Analytics data                 │  │
│  │  ├─ /video/{camera_id}      → MJPEG stream                   │  │
│  │  └─ /event                  → Event ingestion (from worker)  │  │
│  │                                                               │  │
│  │  WebSocket:                                                   │  │
│  │  └─ /ws/alerts              → Real-time alert broadcast      │  │
│  │                                                               │  │
│  │  Middleware:                                                  │  │
│  │  - CORS (configured for frontend origin)                     │  │
│  │  - Static files (frame serving)                              │  │
│  │                                                               │  │
│  │  Services:                                                    │  │
│  │  ├─ Event Engine (event_engine/engine.py)                    │  │
│  │  └─ Alert Service (alert_service/service.py)                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│         │                                                            │
│         │ Data Access                                               │
│         ▼                                                            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       DATA LAYER                                     │
│                                                                      │
│  ┌─────────────────────┐   ┌─────────────────────┐                 │
│  │  In-Memory State    │   │  Redis [PLANNED]    │                 │
│  │  (Development)      │   │  (Production)       │                 │
│  ├─────────────────────┤   ├─────────────────────┤                 │
│  │ • camera_configs    │   │ • camera:*          │                 │
│  │ • incidents         │   │ • worker:*          │                 │
│  │ • alerts_history    │   │ • incident:*        │                 │
│  │ • active_clients    │   │ • alerts:queue      │                 │
│  └─────────────────────┘   └─────────────────────┘                 │
│                                                                      │
│  ┌─────────────────────┐   ┌─────────────────────┐                 │
│  │  JSON Files         │   │  PostgreSQL         │                 │
│  │  [PLANNED]          │   │  [FUTURE]           │                 │
│  ├─────────────────────┤   ├─────────────────────┤                 │
│  │ • tenants/*.json    │   │ • tenants           │                 │
│  │ • cameras/*.json    │   │ • cameras           │                 │
│  │ • incidents/*.json  │   │ • incidents         │                 │
│  └─────────────────────┘   │ • users             │                 │
│                             │ • analytics_agg     │                 │
│                             └─────────────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     AI PROCESSING LAYER                              │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  AI Worker Cluster (YOLOv8 + DeepSORT)                       │  │
│  │                                                               │  │
│  │  Zone-Based Pipelines:                                        │  │
│  │  ├─ Outgate (vehicle detection, gate accidents)              │  │
│  │  ├─ Corridor (crowd formation, fights, weapons)              │  │
│  │  ├─ School Ground (crowd monitoring, violence)               │  │
│  │  └─ Classroom (mobile phone usage, attendance)               │  │
│  │                                                               │  │
│  │  Detection Pipeline:                                          │  │
│  │  1. Video Stream Ingestion (RTSP/File)                       │  │
│  │  2. YOLOv8 Object Detection                                  │  │
│  │  3. DeepSORT Multi-Object Tracking                           │  │
│  │  4. Zone-Specific Behavior Analysis                          │  │
│  │  5. Event Engine Evaluation                                  │  │
│  │  6. Alert Generation (if threat detected)                    │  │
│  │  7. Event POST to Backend                                    │  │
│  │                                                               │  │
│  │  Models:                                                      │  │
│  │  - yolov8n.pt (fast, general)                                │  │
│  │  - yolov8s.pt (balanced)                                     │  │
│  │  - yolov8m.pt (accurate, classroom)                          │  │
│  │  - yolov8n-pose.pt (pose estimation)                         │  │
│  │  - weapon_model.pt (weapon detection)                        │  │
│  │  - gun_model.pt (firearm detection)                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│         │                                                            │
│         │ Video Streams                                             │
│         ▼                                                            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       VIDEO SOURCES                                  │
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │   RTSP Cameras  │  │  Video Files    │  │  IP Cameras     │    │
│  │   (Live)        │  │  (Testing)      │  │  (DVR/NVR)      │    │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### Frontend Component Hierarchy

```
pages/
├─ _app.js                    → ThemeProvider, ToastProvider wrapping
├─ _document.js               → Inter font, favicon, meta tags
├─ index.js                   → Landing/Config page
│                                ├─ ModuleSelector (card-based)
│                                ├─ Camera table with CRUD
│                                └─ Modal forms (AddCameraForm)
├─ setup.js [PLANNED]         → Step-based Setup Wizard
├─ monitor.js                 → Main monitoring dashboard
│  └─ Tabs:
│     ├─ monitoring           → Live camera grid + alerts panel
│     ├─ cameras              → Camera management
│     ├─ incidents            → IncidentTimeline component
│     ├─ analytics            → AnalyticsCharts component
│     └─ settings [PLANNED]   → Settings panel
└─ login.js [PLANNED]         → Google OAuth

components/
├─ layout/
│  ├─ Sidebar.js              → Nav menu, theme toggle, WS status
│  ├─ TopBar.js               → Stats, alert bell, user menu
│  └─ index.js                → DashboardLayout wrapper
│
├─ ui/
│  ├─ Card.js                 → Card, CardHeader, CardTitle, CardContent
│  ├─ Badge.js                → Priority/status badges
│  ├─ Button.js               → Primary, secondary, ghost variants
│  ├─ StatBox.js              → Animated stat counters
│  ├─ StatusIndicator.js      → Online/offline, LiveIndicator
│  ├─ Input.js                → Input, Select, Checkbox
│  ├─ Modal.js                → Dialog/modal component
│  ├─ Skeleton.js             → Loading skeletons
│  ├─ EmptyState.js           → Empty states (NoIncidents, etc.)
│  ├─ Toast.js                → Toast notification system
│  └─ index.js                → Barrel exports
│
├─ AlertPopupNew.js           → Animated alert popup with actions
├─ IncidentTimeline.js        → Incident list with filters/pagination
├─ AnalyticsCharts.js         → Recharts visualizations
├─ CameraFeed.js              → MJPEG video feed component
├─ MultiCameraGrid.js         → Camera grid layout
├─ AddCameraForm.js           → Camera creation form
└─ ModuleSelector.js          → Module selection cards

hooks/
├─ useWebSocket.js            → WebSocket with auto-reconnect
├─ useTheme.js                → Theme switching
└─ useToast.js                → Toast notifications

contexts/
└─ ThemeContext.js            → Theme provider

lib/
├─ constants.js               → API URLs, zones, modules, colors
└─ utils.js                   → Helper functions (cn, formatters)
```

---

## Backend Module Architecture

```
backend/
├─ main.py                    → FastAPI app, all endpoints
│  ├─ CORS middleware
│  ├─ Static file serving
│  ├─ REST endpoints
│  ├─ WebSocket handler
│  └─ In-memory state
│
├─ event_engine/
│  └─ engine.py               → process_event(event) → incident analysis
│
├─ alert_service/
│  └─ service.py              → trigger_alert(incident) → alert generation
│
└─ [PLANNED] services/
   ├─ tenant_service.py       → Tenant CRUD
   ├─ camera_service.py       → Camera management with tenant context
   ├─ incident_service.py     → Incident storage/retrieval
   └─ auth_service.py         → OAuth + session management
```

---

## AI Worker Architecture

```
ai_worker/
├─ worker.py                  → Main worker orchestrator
│  ├─ Polls /api/cameras
│  ├─ Spawns zone-specific pipelines
│  └─ Posts events to /event
│
├─ zones/
│  ├─ base.py                 → BaseZone class
│  ├─ outgate.py              → OutgateZone (vehicle detection)
│  ├─ corridor.py             → CorridorZone (crowd, fights)
│  ├─ school_ground.py        → SchoolGroundZone (outdoor)
│  └─ classroom.py            → ClassroomZone (mobile phones)
│
├─ detectors.py               → Shared detector classes
│  ├─ YOLODetector
│  ├─ WeaponDetector
│  ├─ GunDetector
│  └─ PoseDetector
│
├─ behaviours.py              → Behavior analysis functions
│  ├─ detect_crowd_formation()
│  ├─ detect_fight()
│  ├─ detect_mobile_phone_usage()
│  └─ detect_gate_accident()
│
├─ reid.py                    → DeepSORT tracker
│
├─ registry.py                → Zone registry
│
└─ models/                    → YOLO model weights
   ├─ yolov8n.pt
   ├─ yolov8s.pt
   ├─ yolov8m.pt
   ├─ yolov8n-pose.pt
   ├─ weapon_model.pt
   └─ gun_model.pt
```

---

## Data Flow Sequence

### 1. Camera Registration Flow
```
User (Frontend)
  → POST /api/camera { name, rtsp_url, zone }
    → Backend saves to camera_configs
      → Returns camera_id
        → Worker polls /api/cameras
          → Discovers new camera
            → Spawns zone pipeline
              → Starts processing stream
```

### 2. Detection & Alert Flow
```
AI Worker
  → Opens video stream
    → Runs YOLO detection
      → Tracks objects (DeepSORT)
        → Analyzes behavior (zone-specific)
          → Evaluates threat (Event Engine)
            → If incident:
              → POST /event to Backend
                → Backend processes event
                  → Generates alert (Alert Service)
                    → Stores in incidents dict
                      → Broadcasts via WebSocket
                        → Frontend receives alert
                          → Displays AlertPopup
                            → User takes action
```

### 3. Real-Time Monitoring Flow
```
User navigates to /monitor
  → Frontend establishes WS connection
    → Backend adds client to active_alert_clients
      → Worker posts new event
        → Backend broadcasts to all WS clients
          → Frontend useWebSocket hook receives
            → Deduplicates alert
              → Updates alerts state
                → AlertPopup animates in
                  → Camera highlighted in grid
```

---

## Security & Authentication [PLANNED]

### OAuth Flow
```
User → Login Page
  → Click "Sign in with Google"
    → Redirect to Google OAuth
      → User authenticates
        → Google returns auth code
          → Backend exchanges for tokens
            → Creates/retrieves user + tenant
              → Issues session token (JWT)
                → Stores in httpOnly cookie
                  → Frontend redirects to dashboard
```

### API Security
```
Middleware:
  - CORS (origin validation)
  - Rate limiting (per tenant)
  - JWT validation (for protected routes)

Protected Routes:
  - /api/* (requires valid session)
  - /ws/alerts (requires auth token)

Public Routes:
  - /login
  - /oauth/callback
```

---

## Scalability Considerations

### Current (Single-Server)
- In-memory state
- Single FastAPI process
- Worker runs locally
- No load balancing

### Near-Term (Multi-Worker)
- Redis for shared state
- Multiple worker processes per zone
- Load balancer for backend
- Sticky sessions for WebSocket

### Future (Distributed)
- Kubernetes cluster
- Redis Cluster
- PostgreSQL with read replicas
- Kafka for event streaming
- S3 for frame storage
- CDN for video delivery

---

## Technology Stack Summary

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| **Frontend** | Next.js | 14.0.0 | React framework |
| | React | 18.2.0 | UI library |
| | Tailwind CSS | 3.4.0 | Styling |
| | Framer Motion | - | Animations |
| | Recharts | - | Charts |
| | Lucide React | - | Icons |
| **Backend** | FastAPI | - | API server |
| | Python | 3.10+ | Language |
| | Uvicorn | - | ASGI server |
| | WebSockets | - | Real-time |
| **AI** | YOLOv8 | - | Object detection |
| | DeepSORT | - | Object tracking |
| | OpenCV | - | Video processing |
| | Ultralytics | - | YOLO wrapper |
| **Data** | In-Memory | - | Current (dev) |
| | JSON Files | - | Planned (interim) |
| | Redis | - | Planned (cache) |
| | PostgreSQL | - | Future (DB) |

---

## Deployment Architecture [FUTURE]

```
┌─────────────────────────────────────────────────────────────┐
│                    Load Balancer / CDN                       │
│                    (CloudFlare / Nginx)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┴────────────────┐
       │                                │
┌──────▼──────┐                 ┌───────▼──────┐
│  Frontend   │                 │   Backend    │
│  (Vercel)   │                 │  (Railway)   │
│  Next.js    │◄───WebSocket────│  FastAPI     │
└─────────────┘                 └───────┬──────┘
                                        │
                         ┌──────────────┼──────────────┐
                         │              │              │
                  ┌──────▼─────┐ ┌─────▼──────┐ ┌────▼─────┐
                  │   Redis    │ │ PostgreSQL │ │ S3/Blob  │
                  │  (Upstash) │ │  (Railway) │ │ (Frames) │
                  └────────────┘ └────────────┘ └──────────┘

┌─────────────────────────────────────────────────────────────┐
│               AI Worker Cluster                              │
│               (Separate server with GPU)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │ Worker 1 │ │ Worker 2 │ │ Worker 3 │ │ Worker N │      │
│  │ (Zone A) │ │ (Zone B) │ │ (Zone C) │ │ (Zone D) │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## Monitoring & Observability [PLANNED]

- **Health Checks**: `/api/system/health`, `/api/camera/{id}/health`
- **Logging**: Structured logs (JSON) with log levels
- **Metrics**: Prometheus metrics for API latency, worker FPS, alert counts
- **Tracing**: OpenTelemetry for distributed tracing
- **Dashboards**: Grafana for system monitoring
- **Alerts**: PagerDuty for critical system failures

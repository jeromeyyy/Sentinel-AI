// ─── API Configuration ───────────────────────────────────────────────────────
// Backend URL (configured via NEXT_PUBLIC_API_BASE environment variable)
// No hardcoded fallback - must be set in .env.local or .env.production

const DEFAULT_API_BASE = process.env.NODE_ENV === 'production' 
  ? 'https://sentinelai-backend-c81f.onrender.com'
  : 'http://localhost:8000';

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.NEXT_PUBLIC_API_BASE || DEFAULT_API_BASE;

export const BACKEND_URL = API_BASE;

export const getWsUrl = () => {
  const base = BACKEND_URL;
  if (!base) {
    console.error('❌ Cannot generate WebSocket URL: BACKEND_URL is not configured');
    return '';
  }
  if (base.startsWith('https://')) {
    return base.replace('https://', 'wss://') + '/ws/alerts';
  }
  return base.replace('http://', 'ws://') + '/ws/alerts';
};

// ─── Color System ────────────────────────────────────────────────────────────
export const PRIORITY_COLORS = {
  critical: {
    bg: 'bg-red-500/20',
    border: 'border-red-500',
    text: 'text-red-400',
    dot: 'bg-red-500',
    gradient: 'from-red-500/20 to-transparent',
  },
  high: {
    bg: 'bg-orange-500/20',
    border: 'border-orange-500',
    text: 'text-orange-400',
    dot: 'bg-orange-500',
    gradient: 'from-orange-500/20 to-transparent',
  },
  medium: {
    bg: 'bg-yellow-500/20',
    border: 'border-yellow-500',
    text: 'text-yellow-400',
    dot: 'bg-yellow-500',
    gradient: 'from-yellow-500/20 to-transparent',
  },
  low: {
    bg: 'bg-blue-500/20',
    border: 'border-blue-500',
    text: 'text-blue-400',
    dot: 'bg-blue-500',
    gradient: 'from-blue-500/20 to-transparent',
  },
};

export const STATUS_COLORS = {
  online: { bg: 'bg-green-500', text: 'text-green-400' },
  offline: { bg: 'bg-red-500', text: 'text-red-400' },
  connecting: { bg: 'bg-yellow-500', text: 'text-yellow-400' },
  error: { bg: 'bg-red-500', text: 'text-red-400' },
};

// ─── Zone Definitions ────────────────────────────────────────────────────────
export const ZONES = [
  { 
    id: 'all', 
    label: 'All Zones', 
    description: 'Multi-Detection',
    icon: 'Search',
    model: 'ALL',
    color: 'purple'
  },
  { 
    id: 'outgate', 
    label: 'Outgate', 
    description: 'Vehicle & accident detection',
    icon: 'Car',
    model: 'yolov8n.pt',
    color: 'blue'
  },
  { 
    id: 'corridor', 
    label: 'Corridor', 
    description: 'Crowd & fight detection',
    icon: 'Users',
    model: 'yolov8s.pt',
    color: 'green'
  },
  { 
    id: 'school_ground', 
    label: 'School Ground', 
    description: 'Violence & weapon detection',
    icon: 'MapPin',
    model: 'yolov8s.pt',
    color: 'orange'
  },
  { 
    id: 'classroom', 
    label: 'Classroom', 
    description: 'Mobile phone detection',
    icon: 'BookOpen',
    model: 'yolov8m.pt',
    color: 'cyan'
  },
  {
    id: 'workspace',
    label: 'Workspace',
    description: 'Fire and smoke monitoring',
    icon: 'Flame',
    model: 'fire_smoke_model.pt',
    color: 'orange',
    runtimeZone: 'fire_only',
  },
  {
    id: 'hallway',
    label: 'Hallway',
    description: 'Fire and smoke monitoring',
    icon: 'Flame',
    model: 'fire_smoke_model.pt',
    color: 'orange',
    runtimeZone: 'fire_only',
  },
  {
    id: 'meeting_hall',
    label: 'Meeting Hall',
    description: 'Fire and smoke monitoring',
    icon: 'Flame',
    model: 'fire_smoke_model.pt',
    color: 'orange',
    runtimeZone: 'fire_only',
  },
  {
    id: 'server_room',
    label: 'Server Room',
    description: 'Corridor behavior + safety monitoring',
    icon: 'Server',
    model: 'yolov8s.pt',
    color: 'green',
    runtimeZone: 'corridor',
  },
  {
    id: 'door',
    label: 'Door',
    description: 'Corridor behavior + safety monitoring',
    icon: 'DoorOpen',
    model: 'yolov8s.pt',
    color: 'green',
    runtimeZone: 'corridor',
  },
  {
    id: 'parking',
    label: 'Parking',
    description: 'Ground area behavior monitoring',
    icon: 'SquareParking',
    model: 'yolov8s.pt',
    color: 'orange',
    runtimeZone: 'school_ground',
  },
  {
    id: 'main_gate',
    label: 'Main Gate',
    description: 'Vehicle and gate monitoring',
    icon: 'Gate',
    model: 'yolov8n.pt',
    color: 'blue',
    runtimeZone: 'outgate',
  },
  {
    id: 'living_room',
    label: 'Living Room',
    description: 'Fire and smoke monitoring',
    icon: 'Flame',
    model: 'fire_smoke_model.pt',
    color: 'orange',
    runtimeZone: 'fire_only',
  },
];

export const MODULE_ZONE_IDS = {
  school: ['outgate', 'corridor', 'school_ground', 'classroom'],
  office: ['workspace', 'hallway', 'meeting_hall', 'server_room'],
  home: ['door', 'parking', 'main_gate', 'living_room'],
};

export const getZonesForModule = (moduleId = 'school', options = {}) => {
  const { includeAll = false } = options;
  const zoneIds = MODULE_ZONE_IDS[moduleId] || MODULE_ZONE_IDS.school;

  return ZONES.filter(zone => {
    if (zone.id === 'all') {
      return includeAll;
    }
    return zoneIds.includes(zone.id);
  });
};

export const DEFAULT_CAMERAS = [
  { id: 'cam_outgate', name: 'Outgate Camera', zone: 'outgate', active: true, status: 'online' },
  { id: 'cam_corridor', name: 'Corridor Camera', zone: 'corridor', active: true, status: 'online' },
  { id: 'cam_ground', name: 'School Ground Camera', zone: 'school_ground', active: true, status: 'online' },
  { id: 'cam_classroom', name: 'Classroom Camera', zone: 'classroom', active: true, status: 'online' },
];

// ─── Event Type Labels ───────────────────────────────────────────────────────
export const EVENT_LABELS = {
  vehicle_detected: 'Vehicle Detected',
  gate_accident: 'Gate Accident',
  crowd_formation: 'Crowd Formation',
  fight: 'Fight Detected',
  weapon_detected: 'Weapon Detected',
  fire_smoke_detected: 'Fire/Smoke Detected',
  mobile_usage: 'Mobile Phone Usage',
  fall_detected: 'Fall Detected',
  after_hours_intrusion: 'After Hours Intrusion',
};

// ─── Module Definitions ──────────────────────────────────────────────────────
export const MODULES = [
  { id: 'home', label: 'Home', icon: 'Home', description: 'Home surveillance' },
  { id: 'school', label: 'School', icon: 'GraduationCap', description: 'School monitoring' },
  { id: 'office', label: 'Office', icon: 'Building', description: 'Office security' },
];

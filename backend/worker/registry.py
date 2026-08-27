"""
Model, Tracker, and Environment Registry for SentinelAI.

Manages environment-specific YOLO models, shared detectors, and ByteTrack trackers.

Environments:
- SCHOOL: classroom, corridor, school_ground, outgate, laboratory, exam_hall
- HOME:   entrance, living_room, backyard, kitchen, garage, bedroom
- OFFICE: open_office, server_room, meeting_room, lobby, cafeteria, executive_suite
"""

import os
import logging
import threading
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

# ============================================================================
# YOLO CLASS IDs (COCO standard + custom extensions)
# ============================================================================

COCO_CLASSES = {
    0:  "person",
    1:  "bicycle",
    2:  "car",
    3:  "motorcycle",
    5:  "bus",
    7:  "truck",
    15: "cat",
    16: "dog",
    24: "backpack",
    26: "handbag",
    28: "suitcase",
    43: "knife",
    44: "fork",
    56: "chair",
    57: "couch",
    60: "dining table",
    62: "tv",
    63: "laptop",
    64: "mouse",
    66: "keyboard",
    67: "cell phone",
    73: "book",
    76: "scissors",
}

COCO_WEAPON_CLASSES: Set[int] = {43, 76}          # knife, scissors
VEHICLE_CLASSES: Set[int] = {1, 2, 3, 5, 7}       # bicycle, car, motorcycle, bus, truck
DEVICE_CLASSES: Set[int] = {63, 67}               # laptop, cell phone
PET_CLASSES: Set[int] = {15, 16}                  # cat, dog

# Custom model classes
WEAPON_MODEL_CLASSES = {
    0: "gun",
    1: "knife",
    2: "blade",
    3: "scissors",
}

FIRE_SMOKE_MODEL_CLASSES = {
    0: "fire",
    1: "smoke",
}

# ============================================================================
# ZONE & ENVIRONMENT CONFIGURATIONS
# ============================================================================

@dataclass
class ZoneModelConfig:
    """Configuration for a zone-specific detection model."""
    model_file: str
    confidence_threshold: float
    classes: list
    description: str
    target_fps: int = 5
    iou_threshold: float = 0.45


@dataclass
class EnvironmentConfig:
    """High-level environment definition containing allowed zones and rules."""
    name: str
    description: str
    zones: Dict[str, ZoneModelConfig]
    enabled_rules: List[str]
    default_zone: str


ENVIRONMENT_CONFIGS: Dict[str, EnvironmentConfig] = {
    "school": EnvironmentConfig(
        name="school",
        description="Educational campus safety, violence prevention, exam integrity & facility monitoring",
        default_zone="corridor",
        enabled_rules=[
            "phone_use",
            "fight_altercation",
            "fire_smoke",
            "crowd_density",
            "loitering_dwell",
            "restricted_zone",
            "fall_collapse",
            "after_hours_presence",
            "weapon_detected",
        ],
        zones={
            "classroom": ZoneModelConfig(
                model_file="yolov8m.pt",
                confidence_threshold=0.35,
                classes=[0, 24, 43, 67, 76], # person, backpack, knife, cell phone, scissors
                description="Classroom: Person tracking, mobile phone in-use detection, exam malpractice monitoring",
            ),
            "corridor": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.45,
                classes=[0, 24, 43, 76],
                description="Hallway/Corridor: Physical altercation detection, crowd flow, loitering",
            ),
            "school_ground": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.40,
                classes=[0, 2, 3, 43, 76],
                description="Outdoor Ground: Altercation detection, perimeter weapon security, vehicle perimeter",
            ),
            "outgate": ZoneModelConfig(
                model_file="yolov8n.pt",
                confidence_threshold=0.45,
                classes=[0, 1, 2, 3, 5, 7, 43, 76],
                description="Main Gate / Entry: Vehicle tracking, gate boundary crossings, speed prioritization",
            ),
            "laboratory": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.40,
                classes=[0, 43, 67, 76],
                description="Science Lab: Chemical hazard / fire detection, unauthorized after-hours access",
            ),
            "exam_hall": ZoneModelConfig(
                model_file="yolov8m.pt",
                confidence_threshold=0.35,
                classes=[0, 67, 73], # person, phone, book
                description="Exam Hall: Strict unauthorized device and mobile phone usage detection",
            ),
        }
    ),
    "home": EnvironmentConfig(
        name="home",
        description="Residential security, perimeter intrusion, fall detection, and property protection",
        default_zone="entrance",
        enabled_rules=[
            "intrusion_detected",
            "fire_smoke",
            "fall_collapse",
            "pet_detected",
            "package_detected",
            "loitering_dwell",
            "restricted_zone",
        ],
        zones={
            "entrance": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.45,
                classes=[0, 2, 3, 24, 26, 28], # person, car, motor, backpack, handbag, package
                description="Front Entrance / Porch: Intrusion detection, package delivery, loitering",
            ),
            "living_room": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.40,
                classes=[0, 15, 16, 56, 57], # person, pet, couch
                description="Living Room: Elderly fall detection, unknown presence, pet activity",
            ),
            "backyard": ZoneModelConfig(
                model_file="yolov8n.pt",
                confidence_threshold=0.45,
                classes=[0, 15, 16, 2],
                description="Backyard / Garden: Perimeter boundary breach, animal intrusion",
            ),
            "kitchen": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.45,
                classes=[0, 43], # person, knife
                description="Kitchen: Fire/smoke priority surveillance, unattended burner",
            ),
            "garage": ZoneModelConfig(
                model_file="yolov8n.pt",
                confidence_threshold=0.45,
                classes=[0, 1, 2, 3, 7],
                description="Garage: Vehicle presence, after-hours door intrusion",
            ),
            "bedroom": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.40,
                classes=[0],
                description="Bedroom: Fall monitoring, restricted room access",
            ),
        }
    ),
    "office": EnvironmentConfig(
        name="office",
        description="Corporate facility intelligence, restricted server room access, after-hours security",
        default_zone="open_office",
        enabled_rules=[
            "after_hours_presence",
            "restricted_zone",
            "crowd_density",
            "loitering_dwell",
            "fire_smoke",
            "phone_use",
            "unattended_bag",
        ],
        zones={
            "open_office": ZoneModelConfig(
                model_file="yolov8m.pt",
                confidence_threshold=0.40,
                classes=[0, 24, 63, 67], # person, bag, laptop, phone
                description="Open Workspace: Occupancy tracking, device activity, crowding",
            ),
            "server_room": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.35,
                classes=[0, 24, 28], # strict person, bag detection
                description="Server Room: High-security restricted zone, zero tolerance for unauthorized entry",
            ),
            "meeting_room": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.45,
                classes=[0, 63, 67],
                description="Conference Room: Meeting occupancy, dwell times",
            ),
            "lobby": ZoneModelConfig(
                model_file="yolov8n.pt",
                confidence_threshold=0.45,
                classes=[0, 24, 26, 28],
                description="Reception / Lobby: Visitor traffic, loitering, unattended baggage",
            ),
            "cafeteria": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.45,
                classes=[0, 24],
                description="Cafeteria / Breakroom: High density crowd tracking",
            ),
            "executive_suite": ZoneModelConfig(
                model_file="yolov8s.pt",
                confidence_threshold=0.40,
                classes=[0],
                description="Executive Area: Confidential access perimeter",
            ),
        }
    ),
}

# Flatted lookup for backward compatibility
ZONE_MODEL_CONFIGS: Dict[str, ZoneModelConfig] = {}
for env_name, env_cfg in ENVIRONMENT_CONFIGS.items():
    for z_name, z_cfg in env_cfg.zones.items():
        ZONE_MODEL_CONFIGS[z_name] = z_cfg

# Shared auxiliary model configs
@dataclass
class SharedModelConfig:
    model_file: str
    confidence_threshold: float
    description: str

SHARED_MODEL_CONFIGS: Dict[str, SharedModelConfig] = {
    "pose": SharedModelConfig(
        model_file="yolov8n-pose.pt",
        confidence_threshold=0.45,
        description="Human pose estimation for fight alteration and fall detection (all environments)",
    ),
    "weapon": SharedModelConfig(
        model_file="weapon_model.pt",
        confidence_threshold=0.40,
        description="Ensemble weapon detector: gun, knife, blade, scissors",
    ),
    "gun": SharedModelConfig(
        model_file="gun_model.pt",
        confidence_threshold=0.45,
        description="High-precision gun detection",
    ),
    "fire_smoke": SharedModelConfig(
        model_file="fire_smoke_model.pt",
        confidence_threshold=0.40,
        description="Dedicated dual-class fire and smoke detector",
    ),
}


# ============================================================================
# MODEL REGISTRY
# ============================================================================

class ModelRegistry:
    """
    Thread-safe registry managing YOLO models, shared detectors, and ByteTrack trackers.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._zone_models: Dict[str, Any] = {}
        self._shared_models: Dict[str, Any] = {}
        self._fallback_model = None
        self._initialized = True
        self._load_lock = threading.Lock()

        logging.info("ModelRegistry initialized across School, Home, and Office environments")

    def _get_model_path(self, model_file: str) -> str:
        """Resolve model file path across local models/ directory and environment."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.abspath(os.path.join(base_dir, ".."))
        
        candidates = [
            os.path.join(backend_dir, "models", model_file),
            os.path.join(backend_dir, model_file),
            os.path.join(os.getcwd(), "models", model_file),
            os.path.join(os.getcwd(), "backend", "models", model_file),
            model_file,
        ]
        
        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        
        # Return fallback relative path for ultralytics auto-download
        return model_file

    def get_zone_model(self, zone: str) -> Any:
        """Get or load YOLO model for a specific zone."""
        with self._load_lock:
            if zone in self._zone_models:
                return self._zone_models[zone]

            cfg = ZONE_MODEL_CONFIGS.get(zone)
            if cfg is None:
                # Default to yolov8s.pt
                cfg = ZoneModelConfig(
                    model_file="yolov8s.pt",
                    confidence_threshold=0.45,
                    classes=[0, 43, 67, 76],
                    description="Standard detection model",
                )

            model = self._load_yolo_model(cfg.model_file)
            if model is None:
                model = self._get_fallback_model()

            self._zone_models[zone] = model
            return model

    def get_environment_config(self, environment: str) -> EnvironmentConfig:
        """Get environment configuration."""
        env_key = environment.lower().strip()
        return ENVIRONMENT_CONFIGS.get(env_key, ENVIRONMENT_CONFIGS["school"])

    def get_shared_model(self, model_name: str) -> Optional[Any]:
        """Get or load a shared model (pose, weapon, fire_smoke)."""
        with self._load_lock:
            if model_name in self._shared_models:
                return self._shared_models[model_name]

            cfg = SHARED_MODEL_CONFIGS.get(model_name)
            if cfg is None:
                return None

            model = self._load_yolo_model(cfg.model_file)
            self._shared_models[model_name] = model
            return model

    def get_pose_model(self) -> Optional[Any]:
        return self.get_shared_model("pose")

    def get_weapon_model(self) -> Optional[Any]:
        return self.get_shared_model("weapon")

    def get_gun_model(self) -> Optional[Any]:
        return self.get_shared_model("gun")

    def get_fire_smoke_model(self) -> Optional[Any]:
        return self.get_shared_model("fire_smoke")

    def get_zone_config(self, zone: str) -> ZoneModelConfig:
        return ZONE_MODEL_CONFIGS.get(
            zone,
            ZoneModelConfig("yolov8s.pt", 0.45, [0], "Default fallback"),
        )

    def get_shared_config(self, model_name: str) -> Optional[SharedModelConfig]:
        return SHARED_MODEL_CONFIGS.get(model_name)

    def _load_yolo_model(self, model_file: str) -> Optional[Any]:
        """Load ultralytics YOLO model safely."""
        try:
            from ultralytics import YOLO
            resolved_path = self._get_model_path(model_file)
            logging.info(f"Loading YOLO model from: {resolved_path}")
            model = YOLO(resolved_path)
            return model
        except Exception as e:
            logging.warning(f"Could not load {model_file}: {e}")
            return None

    def _get_fallback_model(self) -> Any:
        if self._fallback_model is None:
            try:
                from ultralytics import YOLO
                path = self._get_model_path("yolov8n.pt")
                self._fallback_model = YOLO(path)
            except Exception as e:
                logging.error(f"Failed to load fallback yolov8n.pt: {e}")
                self._fallback_model = None
        return self._fallback_model
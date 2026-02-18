import requests
import time

def send_event(event):
    resp = requests.post("http://localhost:8000/event", json=event)
    print(resp.json())

# Fight event
send_event({
    "event_id": f"evt_fight_{int(time.time())}",
    "tenant_id": "school1",
    "camera_id": "cam1",
    "event_type": "fight",
    "confidence": 0.85,
    "timestamp": time.time(),
    "bounding_boxes": [[100,100,200,200]],
    "zone": "Corridor A",
    "severity_score": 0.9
})

# Accident event
send_event({
    "event_id": f"evt_accident_{int(time.time())}",
    "tenant_id": "school1",
    "camera_id": "cam1",
    "event_type": "gate_accident",
    "confidence": 0.92,
    "timestamp": time.time(),
    "bounding_boxes": [[50,50,180,180]],
    "zone": "Gate",
    "severity_score": 0.95
})

# Weapon detection event
send_event({
    "event_id": f"evt_weapon_{int(time.time())}",
    "tenant_id": "school1",
    "camera_id": "cam1",
    "event_type": "weapon",
    "confidence": 0.97,
    "timestamp": time.time(),
    "bounding_boxes": [[120,120,160,160]],
    "zone": "Classroom",
    "severity_score": 0.99
})

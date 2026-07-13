"""
MongoDB Atlas Database Connection Module for SentinelAI
Uses motor.motor_asyncio for async MongoDB operations
"""
import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

# Get MongoDB URL from environment
MONGO_URL = os.getenv("MONGO_URL", "")
DATABASE_NAME = "sentinel_ai"

# Global database client and db reference
_client: Optional[AsyncIOMotorClient] = None
db = None


async def connect_db() -> bool:
    """
    Connect to MongoDB Atlas and initialize the database.
    Returns True if connection successful, False otherwise.
    """
    global _client, db
    
    if not MONGO_URL:
        logging.error("[DB] MONGO_URL environment variable not set")
        return False
    
    try:
        logging.info("[DB] Connecting to MongoDB Atlas...")
        _client = AsyncIOMotorClient(MONGO_URL)
        
        # Test connection with ping
        await _client.admin.command('ping')
        logging.info("[DB] MongoDB connection successful")
        
        # Get database reference
        db = _client[DATABASE_NAME]
        logging.info(f"[DB] Using database: {DATABASE_NAME}")
        
        return True
        
    except Exception as e:
        logging.error(f"[DB] Failed to connect to MongoDB: {e}")
        return False


async def create_indexes() -> None:
    """
    Create database indexes for optimal query performance.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot create indexes - database not connected")
        return
    
    try:
        # Incidents collection indexes
        logging.info("[DB] Creating indexes for 'incidents' collection...")
        await db.incidents.create_index("camera_id")
        await db.incidents.create_index("timestamp")
        await db.incidents.create_index("event_type")
        logging.info("[DB] Incidents indexes created: camera_id, timestamp, event_type")
        
        # Cameras collection indexes
        logging.info("[DB] Creating indexes for 'cameras' collection...")
        await db.cameras.create_index("tenant_id")
        await db.cameras.create_index("id", unique=True)
        logging.info("[DB] Cameras indexes created: tenant_id, id (unique)")
        
    except Exception as e:
        logging.error(f"[DB] Failed to create indexes: {e}")


async def close_db() -> None:
    """
    Close the MongoDB connection gracefully.
    """
    global _client, db
    
    if _client:
        logging.info("[DB] Closing MongoDB connection...")
        _client.close()
        _client = None
        db = None
        logging.info("[DB] MongoDB connection closed")


async def init_db() -> bool:
    """
    Initialize database connection and create indexes.
    Returns True if successful, False otherwise.
    """
    connected = await connect_db()
    if connected:
        await create_indexes()
    return connected


# Helper functions for common operations
async def insert_incident(incident_data: dict) -> Optional[str]:
    """
    Insert an incident into the database.
    Returns the inserted document ID or None on failure.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot insert incident - database not connected")
        return None
    
    try:
        result = await db.incidents.insert_one(incident_data)
        return str(result.inserted_id)
    except Exception as e:
        logging.error(f"[DB] Failed to insert incident: {e}")
        return None


async def get_incidents(filter_query: dict = None, limit: int = 100) -> list:
    """
    Get incidents from the database.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot get incidents - database not connected")
        return []
    
    try:
        query = filter_query or {}
        cursor = db.incidents.find(query).sort("timestamp", -1).limit(limit)
        incidents = await cursor.to_list(length=limit)
        # Convert ObjectId to string for JSON serialization
        for incident in incidents:
            incident["_id"] = str(incident["_id"])
        return incidents
    except Exception as e:
        logging.error(f"[DB] Failed to get incidents: {e}")
        return []


async def get_all_cameras(tenant_id: str = None) -> list:
    """
    Get all cameras from the database.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot get cameras - database not connected")
        return []
    
    try:
        query = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        cursor = db.cameras.find(query)
        cameras = await cursor.to_list(length=1000)
        # Convert ObjectId to string for JSON serialization
        for camera in cameras:
            camera["_id"] = str(camera["_id"])
        return cameras
    except Exception as e:
        logging.error(f"[DB] Failed to get cameras: {e}")
        return []


async def get_camera_by_id(camera_id: str) -> Optional[dict]:
    """
    Get a single camera by ID.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot get camera - database not connected")
        return None
    
    try:
        camera = await db.cameras.find_one({"id": camera_id})
        if camera:
            camera["_id"] = str(camera["_id"])
        return camera
    except Exception as e:
        logging.error(f"[DB] Failed to get camera {camera_id}: {e}")
        return None


async def upsert_camera(camera_data: dict) -> bool:
    """
    Insert or update a camera in the database.
    Uses the 'id' field for matching.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot upsert camera - database not connected")
        return False
    
    try:
        camera_id = camera_data.get("id")
        if not camera_id:
            logging.error("[DB] Camera data must have 'id' field")
            return False
        
        result = await db.cameras.update_one(
            {"id": camera_id},
            {"$set": camera_data},
            upsert=True
        )
        return True
    except Exception as e:
        logging.error(f"[DB] Failed to upsert camera: {e}")
        return False


async def delete_camera_by_id(camera_id: str) -> bool:
    """
    Delete a camera by ID.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot delete camera - database not connected")
        return False
    
    try:
        result = await db.cameras.delete_one({"id": camera_id})
        return result.deleted_count > 0
    except Exception as e:
        logging.error(f"[DB] Failed to delete camera {camera_id}: {e}")
        return False


async def update_incident_resolved(event_id: str, resolved: bool = True) -> bool:
    """
    Update an incident's resolved status.
    """
    global db
    
    if db is None:
        logging.warning("[DB] Cannot update incident - database not connected")
        return False
    
    try:
        result = await db.incidents.update_one(
            {"event_id": event_id},
            {"$set": {"resolved": resolved}}
        )
        return result.modified_count > 0
    except Exception as e:
        logging.error(f"[DB] Failed to update incident {event_id}: {e}")
        return False

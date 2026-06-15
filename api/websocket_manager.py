import asyncio
import logging
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger("opspilot.websocket_manager")

class ConnectionManager:
    """
    Manages active WebSocket connections per incident_id to stream investigation status.
    """
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, incident_id: str):
        await websocket.accept()
        async with self.lock:
            if incident_id not in self.active_connections:
                self.active_connections[incident_id] = []
            self.active_connections[incident_id].append(websocket)
        logger.info(f"WebSocket connected for incident {incident_id}. Total connections: {len(self.active_connections[incident_id])}")

    async def disconnect(self, websocket: WebSocket, incident_id: str):
        async with self.lock:
            if incident_id in self.active_connections:
                if websocket in self.active_connections[incident_id]:
                    self.active_connections[incident_id].remove(websocket)
                if not self.active_connections[incident_id]:
                    del self.active_connections[incident_id]
        logger.info(f"WebSocket disconnected for incident {incident_id}.")

    async def send_status(
        self,
        incident_id: str,
        agent: str,
        status: str,
        message: str = None,
        tools: list = None,
        data: dict = None
    ):
        """
        Sends agent status update to all WebSocket connections listening on incident_id.
        """
        async with self.lock:
            connections = self.active_connections.get(incident_id, [])[:]
            
        if not connections:
            logger.debug(f"No active WebSocket connections for incident {incident_id}")
            return
            
        payload = {
            "agent": agent,
            "status": status
        }
        if message is not None:
            payload["message"] = message
        if tools is not None:
            payload["tools"] = tools
        if data is not None:
            payload["data"] = data
            
        logger.info(f"Streaming status: {payload} to incident {incident_id}")
        
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception as e:
                logger.warning(f"Failed to send JSON to websocket for incident {incident_id}: {e}")

# Singleton manager instance
manager = ConnectionManager()

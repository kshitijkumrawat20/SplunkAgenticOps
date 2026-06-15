import logging
from typing import Dict, Any
from agents.state import IncidentState
from memory.incident_store import load_similar_incidents
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.memory_agent")

async def memory_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Memory Agent Node:
    Queries historical incidents from memory/incidents.json based on current service and error details.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "memory_agent", 
            "running",
            message="Searching local vector/JSON store for similar historical outages..."
        )
        
    logger.info("Starting Memory Agent...")
    
    log = state.get("log_findings")
    service_name = ""
    error_types = []
    
    if log:
        if hasattr(log, "affected_services") and log.affected_services:
            service_name = log.affected_services[0]
        elif isinstance(log, dict) and log.get("affected_services"):
            service_name = log["affected_services"][0]
            
        if hasattr(log, "dominant_errors") and log.dominant_errors:
            error_types = log.dominant_errors
        elif isinstance(log, dict) and log.get("dominant_errors"):
            error_types = log["dominant_errors"]
            
    # Retrieve incident classification and industry type
    classification = state.get("classification_findings")
    if isinstance(classification, dict):
        incident_type = classification.get("incident_type", "unknown")
    else:
        incident_type = getattr(classification, "incident_type", "unknown") if classification else "unknown"
    from config.environment import get_active_profile
    active_profile = get_active_profile()
    industry = active_profile.environment_type

    # Load similar incidents from local history
    historical_context = load_similar_incidents(
        service_name=service_name,
        error_types=error_types,
        incident_type=incident_type,
        industry=industry
    )
    logger.info(f"Memory Agent findings: {historical_context}")
    
    if incident_id:
        await manager.send_status(
            incident_id, 
            "memory_agent", 
            "completed",
            message=f"Memory check complete. Found {historical_context['similar_incidents_found']} similar incidents. Recommended fix: '{historical_context['recommended_fix']}'",
            data=historical_context
        )
        
    return {
        "historical_context": historical_context
    }

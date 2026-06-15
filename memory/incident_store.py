import os
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("opspilot.incident_store")
STORE_PATH = os.path.join(os.path.dirname(__file__), "incidents.json")

def _load_store() -> List[Dict[str, Any]]:
    if not os.path.exists(STORE_PATH):
        return []
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except Exception as e:
        logger.error(f"Failed to read incident store: {e}")
        return []

def _save_store(data: List[Dict[str, Any]]):
    try:
        os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write to incident store: {e}")

def save_incident(incident: Dict[str, Any]):
    """
    Saves an incident's execution outcome to history.
    """
    logger.info(f"Saving incident {incident.get('incident_id')} to memory...")
    store = _load_store()
    # Check for duplicate incident_id to update or append
    incident_id = incident.get("incident_id")
    existing_index = next((i for i, item in enumerate(store) if item.get("incident_id") == incident_id), None)
    
    if existing_index is not None:
        store[existing_index] = incident
    else:
        store.append(incident)
        
    _save_store(store)

def load_similar_incidents(service_name: str, error_types: List[str], incident_type: Optional[str] = None, industry: Optional[str] = None, limit: int = 3) -> Dict[str, Any]:
    """
    Loads historical incidents that match the service_name, error_types, incident_type, industry, or root cause keywords,
    and returns aggregated context.
    """
    store = _load_store()
    matches = []
    
    for incident in store:
        score = 0
        incident_service = incident.get("affected_service", "").lower()
        incident_rc = incident.get("root_cause", "").lower()
        incident_industry = incident.get("industry", "").lower()
        incident_type_val = incident.get("incident_type", "").lower()
        
        # Match industry profile
        if industry and incident_industry == industry.lower():
            score += 4
            
        # Match incident type category
        if incident_type and incident_type_val == incident_type.lower():
            score += 3

        # Match service name
        if service_name and service_name.lower() in incident_service:
            score += 2
            
        # Match error types
        for err in error_types:
            err_lower = err.lower()
            if err_lower in incident_rc or err_lower in incident_service:
                score += 1
                
        if score > 0:
            matches.append((score, incident))
            
    # Sort matches by score descending
    matches.sort(key=lambda x: x[0], reverse=True)
    matched_incidents = [m[1] for m in matches[:limit]]
    
    similar_incidents_found = len(matched_incidents)
    
    if similar_incidents_found > 0:
        # Calculate success rate of matches
        successes = sum(1 for inc in matched_incidents if inc.get("success", False))
        historical_success_rate = round(successes / similar_incidents_found, 2)
        
        # Recommended fix from the best match's first remediation step or join them
        best_match = matched_incidents[0]
        remed = best_match.get("remediation", [])
        if isinstance(remed, list) and remed:
            recommended_fix = remed[0]
        elif isinstance(remed, str) and remed:
            recommended_fix = remed
        else:
            recommended_fix = f"rollback {service_name}"
    else:
        # Defaults if no history found
        recommended_fix = f"rollback {service_name}" if service_name else "restart service"
        historical_success_rate = 1.0  # Default success rate
        
    return {
        "similar_incidents_found": similar_incidents_found,
        "recommended_fix": recommended_fix,
        "historical_success_rate": historical_success_rate
    }

def search_incident_history(query: str) -> List[Dict[str, Any]]:
    """
    Searches historical incidents by query string matching service, root cause, or remediation steps.
    """
    store = _load_store()
    if not query:
        return store
        
    query_lower = query.lower()
    results = []
    for inc in store:
        service = inc.get("affected_service", "").lower()
        rc = inc.get("root_cause", "").lower()
        remed = str(inc.get("remediation", "")).lower()
        
        if query_lower in service or query_lower in rc or query_lower in remed:
            results.append(inc)
    return results

def get_all_incidents() -> List[Dict[str, Any]]:
    return _load_store()

def get_incident_by_id(incident_id: str) -> Optional[Dict[str, Any]]:
    store = _load_store()
    return next((inc for inc in store if inc.get("incident_id") == incident_id), None)

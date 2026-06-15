import os
import logging
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import ClassificationFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.websocket_manager import manager
from config.environment import get_active_profile

logger = logging.getLogger("opspilot.classification_agent")

async def classification_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Classification Agent Node:
    Inspects the incident alert details and current profile context to classify
    the incident type, severity, affected domain, and confidence.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "classification_agent", 
            "running",
            message="Classifying incident using current profile context..."
        )
        
    logger.info("Starting Classification Agent...")
    
    active_profile = get_active_profile()
    profile_dict = active_profile.to_dict()
    
    alert_name = state.get("alert_name", "Unknown Incident")
    error_query = state.get("error_query", "")
    
    prompt = f"""
    You are the Classification Agent of OpsPilot AI. Analyze the alert name, search query, and environment profile configuration to classify the incident.
    
    Alert Name: {alert_name}
    Search Query: {error_query}
    
    Current Environment Profile Configuration:
    - Environment Type: {profile_dict['environment_type']}
    - Services: {profile_dict['services']}
    - Critical Components: {profile_dict['critical_components']}
    - Allowed Error Categories: {profile_dict['error_categories']}
    - Business Entities: {profile_dict['business_entities']}
    
    Please formulate a ClassificationFinding JSON containing:
    - incident_type: Categorize this incident into one of the following exact types:
      'database', 'cache', 'networking', 'deployment', 'infrastructure', 'application', 'security', 'unknown'
      Choose the most appropriate category based on the services, critical components, and error categories in the active profile.
    - severity: Choose one of 'low', 'medium', 'high', 'critical'
    - affected_domain: Identify the specific service or domain component affected (e.g. order-service or postgres or redis, etc. matching the current profile)
    - confidence: A confidence level between 0.0 and 1.0 based on how clearly the alert maps to the profile context.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    
    classification_llm = llm.with_structured_output(ClassificationFinding)
    
    try:
        findings = classification_llm.invoke(prompt)
        logger.info(f"Classification findings: {findings}")
    except Exception as e:
        logger.error(f"Failed to run classification: {e}")
        # Fallback classification finding
        findings = ClassificationFinding(
            incident_type="unknown",
            severity="medium",
            affected_domain="unknown",
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "classification_agent", 
            "completed",
            message=f"Classification complete. Incident type: {findings.incident_type}, severity: {findings.severity}, domain: {findings.affected_domain}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "classification_findings": findings
    }

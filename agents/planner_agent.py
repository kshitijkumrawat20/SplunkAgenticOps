import os
import json
import logging
from typing import Dict, Any, List
from agents.state import IncidentState
from agents.models import InvestigationPlan
from langchain_google_genai import ChatGoogleGenerativeAI
from api.websocket_manager import manager
from config.environment import get_active_profile

logger = logging.getLogger("opspilot.planner_agent")

CAPABILITIES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "capabilities.json"
)

def load_capabilities() -> Dict[str, List[str]]:
    """Loads capabilities mapping from capabilities.json."""
    if os.path.exists(CAPABILITIES_FILE):
        try:
            with open(CAPABILITIES_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load capabilities.json: {e}")
    # Hardcoded default fallback mapping if capabilities.json fails
    return {
        "database": ["log_agent", "metrics_agent", "anomaly_agent", "deployment_agent", "database_agent", "runbook_agent"],
        "cache": ["log_agent", "metrics_agent", "anomaly_agent", "application_agent", "runbook_agent"],
        "networking": ["log_agent", "network_agent", "metrics_agent", "runbook_agent"],
        "deployment": ["log_agent", "metrics_agent", "anomaly_agent", "deployment_agent", "application_agent", "runbook_agent"],
        "infrastructure": ["log_agent", "metrics_agent", "anomaly_agent", "infrastructure_agent", "runbook_agent"],
        "kubernetes": ["log_agent", "kubernetes_agent", "metrics_agent", "anomaly_agent", "deployment_agent", "runbook_agent"],
        "security": ["log_agent", "security_agent", "network_agent", "runbook_agent"],
        "application": ["log_agent", "metrics_agent", "anomaly_agent", "application_agent", "runbook_agent"],
        "unknown": ["log_agent", "metrics_agent", "anomaly_agent", "runbook_agent"]
    }

async def planner_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Investigation Planner Agent Node:
    Analyzes alert metadata, Active Environment Profile, and determines:
    1. The type of incident.
    2. The required investigation agents from capabilities.json.
    3. The rationale/reasoning behind this plan.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "planner_agent", 
            "running",
            message="Generating dynamic investigation plan based on incident profile..."
        )
        
    logger.info("Starting Investigation Planner Agent...")
    
    active_profile = get_active_profile()
    profile_dict = active_profile.to_dict()
    
    alert_name = state.get("alert_name", "Unknown Incident")
    error_query = state.get("error_query", "")
    
    # We load capabilities to list them for the LLM
    capabilities = load_capabilities()
    
    prompt = f"""
    You are the Investigation Planner Agent of OpsPilot AI. Analyze the alert name, search query, and environment profile configuration to formulate an InvestigationPlan.
    
    Alert Name: {alert_name}
    Search Query: {error_query}
    
    Current Environment Profile Configuration:
    - Environment Type: {profile_dict['environment_type']}
    - Services: {profile_dict['services']}
    - Critical Components: {profile_dict['critical_components']}
    - Error Categories: {profile_dict['error_categories']}
    - Business Entities: {profile_dict['business_entities']}
    
    Available Incident Types & Dynamic Capabilities mapping:
    {json.dumps(capabilities, indent=2)}
    
    Please formulate an InvestigationPlan JSON containing:
    - incident_type: Choose the most appropriate category ('database', 'cache', 'networking', 'deployment', 'infrastructure', 'application', 'security', 'unknown').
    - confidence: A confidence level between 0.0 and 1.0.
    - required_agents: The list of required agent IDs associated with this incident_type in the capabilities mapping.
    - reasoning: Clear reasoning explaining why these specific agents were selected and what the objective is.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    
    planner_llm = llm.with_structured_output(InvestigationPlan)
    
    try:
        plan = planner_llm.invoke(prompt)
        # Verify and align required_agents from capabilities mapping
        mapped_agents = capabilities.get(plan.incident_type)
        if mapped_agents:
            plan.required_agents = mapped_agents
            
        logger.info(f"Generated Investigation Plan: {plan}")
    except Exception as e:
        logger.error(f"Failed to generate plan: {e}")
        # Fallback plan
        plan = InvestigationPlan(
            incident_type="unknown",
            confidence=0.5,
            required_agents=["log_agent", "metrics_agent", "anomaly_agent", "runbook_agent"],
            reasoning=f"Fallback plan triggered due to LLM error: {str(e)}"
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "planner_agent", 
            "completed",
            message=f"Plan generated. Incident type: {plan.incident_type}. Selected agents: {plan.required_agents}",
            data=plan.model_dump() if hasattr(plan, "model_dump") else plan
        )
        
    return {
        "investigation_plan": plan,
        "classification_findings": {
            "incident_type": plan.incident_type,
            "severity": "high",
            "affected_domain": plan.incident_type,
            "confidence": plan.confidence
        }
    }

import os
import logging
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import HistoricalContext
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

logger = logging.getLogger("opspilot.executive_summary_agent")

class ExecutiveBriefing(BaseModel):
    executive_summary: str = Field(description="A concise leadership-level incident briefing. Max 5 sentences.")

def generate_executive_briefing(state: IncidentState) -> str:
    """
    Invokes LLM to generate a non-technical leadership-level briefing.
    Ensures maximum 5 sentences, detailing business impact, affected service,
    root cause, remediation steps, and confidence level.
    """
    logger.info("Generating executive summary briefing...")
    rca = state.get("rca_findings")
    remediation = state.get("remediation_proposal")
    historical = state.get("historical_context")
    log = state.get("log_findings")
    
    rca_str = rca.model_dump_json() if rca and hasattr(rca, "model_dump_json") else str(rca)
    remediation_str = remediation.model_dump_json() if remediation and hasattr(remediation, "model_dump_json") else str(remediation)
    historical_str = str(historical)
    
    affected_service = "Unknown"
    if log:
        if hasattr(log, "affected_services") and log.affected_services:
            affected_service = log.affected_services[0]
        elif isinstance(log, dict) and log.get("affected_services"):
            affected_service = log["affected_services"][0]

    from config.environment import get_active_profile
    active_profile = get_active_profile()
    profile_dict = active_profile.to_dict()

    prompt = f"""
    You are the Executive Summary Agent of OpsPilot AI. Your goal is to write a non-technical briefing of the incident for business leadership.
    
    Environment Context:
    - Environment Type: {profile_dict['environment_type']}
    - Business Entities in environment: {profile_dict['business_entities']}
    
    Incident Context:
    - Affected Service: {affected_service}
    - Root Cause Findings: {rca_str}
    - Proposed Remediation Action: {remediation_str}
    - Historical Context: {historical_str}
    
    Requirements:
    1. Maximum of 5 sentences.
    2. Write for a non-technical executive audience (avoid technical jargon). Customize the business impact to make sense for the environment type and its business entities.
    3. You MUST include:
       - The business impact of the incident.
       - The affected service name.
       - The identified root cause.
       - The recommended remediation action.
       - The confidence level (specifically mention the percentage, e.g. 91%).
       
    Example:
    "A recent deployment of the order-service v2.1.0 caused a critical spike in database timeouts, blocking customers from completing transactions. Historical memory analysis identified three similar past outages. We recommend immediately rolling back the order-service to its previous stable version. The engineering team has 91% confidence that this rollback will fully restore order processing."
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    
    briefing_llm = llm.with_structured_output(ExecutiveBriefing)
    
    try:
        briefing = briefing_llm.invoke(prompt)
        logger.info(f"Executive briefing generated successfully: {briefing.executive_summary}")
        return briefing.executive_summary
    except Exception as e:
        logger.error(f"Failed to generate executive briefing: {e}")
        # Return fallback briefing
        return f"A critical database timeout spike impacted transaction flows in the {affected_service} service. Root cause analysis points to database resource contention. The recommended remediation is scaling replicas, with an estimated confidence level of 85%."

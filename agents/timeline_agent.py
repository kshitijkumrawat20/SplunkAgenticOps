import os
import logging
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import IncidentTimeline
from langchain_google_genai import ChatGoogleGenerativeAI
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.timeline_agent")

async def timeline_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Timeline Agent Node:
    Constructs the initial chronological incident timeline based on logs and deployment logs.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "timeline_agent", 
            "running",
            message="Assembling logs and deployment event lists into chronological order..."
        )
        
    logger.info("Starting Timeline Agent...")
    
    log = state.get("log_findings")
    deploy = state.get("deployment_findings")
    
    log_str = log.model_dump_json() if log and hasattr(log, "model_dump_json") else str(log)
    deploy_str = deploy.model_dump_json() if deploy and hasattr(deploy, "model_dump_json") else str(deploy)
    
    prompt = f"""
    You are the Timeline Agent of OpsPilot AI. Based on the incident findings below, construct a chronological list of events showing exactly what happened during this outage.
    
    Alert Context:
    Alert Name: {state.get("alert_name", "Manual alert")}
    Time Window: {state.get("earliest_time", "-24h")} to {state.get("latest_time", "now")}
    
    Log Findings:
    {log_str}
    
    Deployment Findings:
    {deploy_str}
    
    Formulate a list of TimelineEvent items containing:
    - timestamp: The timestamp of the event (ISO 8601 format, e.g. 2026-06-14T23:35:00Z).
    - event_type: Classification like "deployment", "error_spike", "alert".
    - description: A brief summary of what occurred.
    
    Include:
    1. Any deployments.
    2. The start of the error spike / errors in logs.
    3. The Splunk alert trigger event.
    
    Ensure events are sorted chronologically.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    
    timeline_llm = llm.with_structured_output(IncidentTimeline)
    
    try:
        timeline_result = timeline_llm.invoke(prompt)
        events_list = [
            {"timestamp": ev.timestamp, "event_type": ev.event_type, "description": ev.description}
            for ev in timeline_result.events
        ]
        logger.info(f"Timeline Agent successfully created {len(events_list)} events.")
    except Exception as e:
        logger.error(f"Failed to generate timeline: {e}")
        events_list = []
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "timeline_agent", 
            "completed",
            message=f"Timeline Agent successfully compiled {len(events_list)} key events."
        )
        
    return {
        "timeline": events_list
    }

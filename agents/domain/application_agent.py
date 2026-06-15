import os
import logging
import json
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import DomainAgentFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.application_agent")

async def application_agent_node(state: IncidentState) -> Dict[str, Any]:
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "application_agent", 
            "running",
            message="Application Agent executing domain-specific application diagnostics...",
            tools=["splunk_run_query"]
        )
        
    logger.info("Starting Application Agent...")
    
    # Query Splunk for application-related logs
    index = state.get("index", "opspilot_logs")
    query = f"search index={index} (exception OR error OR traceback OR application OR NullPointer OR crash OR timeout OR endpoint)"
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    
    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=15)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Application Agent query failed: {e}")
        
    log_lines = [r.get("_raw", "") for r in raw_results if r.get("_raw", "")]
    if not log_lines:
        log_lines = ["No application-related logs found in Splunk."]
        
    prompt = f"""
    You are the Application Agent of OpsPilot AI. Analyze the following telemetry logs:
    
    Logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Perform application stack trace, HTTP error code, and exception diagnostics.
    2. Identify software bugs, unhandled exceptions, downstream API timeouts, or null pointer references.
    3. Suggest application remediation actions (e.g. roll back software release, add error handling logic, clear Redis cache).
    
    Provide your diagnostics in a DomainAgentFinding structure.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    app_llm = llm.with_structured_output(DomainAgentFinding)
    
    try:
        findings = app_llm.invoke(prompt)
    except Exception as e:
        logger.error(f"Failed application agent analysis: {e}")
        findings = DomainAgentFinding(
            incident_type="application",
            analysis="Failed to execute LLM analysis on application logs.",
            discovered_issues=["Application diagnostic query failed"],
            suggested_actions=["Check application traceback logs manually"],
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "application_agent", 
            "completed",
            message=f"Application Agent analysis complete. Discovered: {findings.discovered_issues}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    # Store in domain_findings dict
    domain_findings = state.get("domain_findings") or {}
    domain_findings["application_agent"] = findings
    
    return {
        "domain_findings": domain_findings
    }

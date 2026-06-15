import os
import logging
import json
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import DomainAgentFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.security_agent")

async def security_agent_node(state: IncidentState) -> Dict[str, Any]:
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "security_agent", 
            "running",
            message="Security Agent executing domain-specific security diagnostics...",
            tools=["splunk_run_query"]
        )
        
    logger.info("Starting Security Agent...")
    
    # Query Splunk for security-related logs
    index = state.get("index", "opspilot_logs")
    query = f"search index={index} (unauthorized OR permission OR auth OR security OR login OR access OR credential OR token)"
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    
    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=15)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Security Agent query failed: {e}")
        
    log_lines = [r.get("_raw", "") for r in raw_results if r.get("_raw", "")]
    if not log_lines:
        log_lines = ["No security-related logs found in Splunk."]
        
    prompt = f"""
    You are the Security Agent of OpsPilot AI. Analyze the following telemetry logs:
    
    Logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Perform access control, permission validation, and threat signature diagnostics.
    2. Identify security breaches, unauthorized logins, API token leaks, or credential failures.
    3. Suggest security remediation actions (e.g. rotate access tokens, disable compromised user account, enforce IP firewall).
    
    Provide your diagnostics in a DomainAgentFinding structure.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    sec_llm = llm.with_structured_output(DomainAgentFinding)
    
    try:
        findings = sec_llm.invoke(prompt)
    except Exception as e:
        logger.error(f"Failed security agent analysis: {e}")
        findings = DomainAgentFinding(
            incident_type="security",
            analysis="Failed to execute LLM analysis on security logs.",
            discovered_issues=["Security diagnostic query failed"],
            suggested_actions=["Check authorization logs manually"],
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "security_agent", 
            "completed",
            message=f"Security Agent analysis complete. Discovered: {findings.discovered_issues}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    # Store in domain_findings dict
    domain_findings = state.get("domain_findings") or {}
    domain_findings["security_agent"] = findings
    
    return {
        "domain_findings": domain_findings
    }

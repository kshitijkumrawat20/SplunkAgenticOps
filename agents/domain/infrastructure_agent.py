import os
import logging
import json
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import DomainAgentFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.infrastructure_agent")

async def infrastructure_agent_node(state: IncidentState) -> Dict[str, Any]:
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "infrastructure_agent", 
            "running",
            message="Infrastructure Agent executing domain-specific infrastructure diagnostics...",
            tools=["splunk_run_query"]
        )
        
    logger.info("Starting Infrastructure Agent...")
    
    # Query Splunk for infrastructure-related logs
    index = state.get("index", "opspilot_logs")
    query = f"search index={index} (disk OR cpu OR memory OR infrastructure OR host OR server OR hardware OR load)"
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    
    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=15)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Infrastructure Agent query failed: {e}")
        
    log_lines = [r.get("_raw", "") for r in raw_results if r.get("_raw", "")]
    if not log_lines:
        log_lines = ["No infrastructure-related logs found in Splunk."]
        
    prompt = f"""
    You are the Infrastructure Agent of OpsPilot AI. Analyze the following telemetry logs:
    
    Logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Perform infrastructure server host, VM, and compute node diagnostics.
    2. Identify disk space exhaustion, high CPU utilization thresholds, VM lockups, or host hardware issues.
    3. Suggest infrastructure remediation actions (e.g. scale up cluster size, clean up temporary disk files, restart system host).
    
    Provide your diagnostics in a DomainAgentFinding structure.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    infra_llm = llm.with_structured_output(DomainAgentFinding)
    
    try:
        findings = infra_llm.invoke(prompt)
    except Exception as e:
        logger.error(f"Failed infrastructure agent analysis: {e}")
        findings = DomainAgentFinding(
            incident_type="infrastructure",
            analysis="Failed to execute LLM analysis on infrastructure logs.",
            discovered_issues=["Infrastructure diagnostic query failed"],
            suggested_actions=["Check host CPU/disk utilization manually"],
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "infrastructure_agent", 
            "completed",
            message=f"Infrastructure Agent analysis complete. Discovered: {findings.discovered_issues}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    # Store in domain_findings dict
    domain_findings = state.get("domain_findings") or {}
    domain_findings["infrastructure_agent"] = findings
    
    return {
        "domain_findings": domain_findings
    }

import os
import logging
import json
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import DomainAgentFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.network_agent")

async def network_agent_node(state: IncidentState) -> Dict[str, Any]:
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "network_agent", 
            "running",
            message="Network Agent executing domain-specific network diagnostics...",
            tools=["splunk_run_query"]
        )
        
    logger.info("Starting Network Agent...")
    
    # Query Splunk for network-related logs
    index = state.get("index", "opspilot_logs")
    query = f"search index={index} (network OR connect OR connection OR dns OR socket OR port OR host OR tcp OR udp)"
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    
    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=15)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Network Agent query failed: {e}")
        
    log_lines = [r.get("_raw", "") for r in raw_results if r.get("_raw", "")]
    if not log_lines:
        log_lines = ["No network-related logs found in Splunk."]
        
    prompt = f"""
    You are the Network Agent of OpsPilot AI. Analyze the following telemetry logs:
    
    Logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Perform network connection, port mapping, and latency diagnostics.
    2. Identify connection issues, DNS timeouts, socket errors, or packet drops.
    3. Suggest network remediation actions (e.g. check SG group firewall, configure failover DNS, adjust HTTP client timeout).
    
    Provide your diagnostics in a DomainAgentFinding structure.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    net_llm = llm.with_structured_output(DomainAgentFinding)
    
    try:
        findings = net_llm.invoke(prompt)
    except Exception as e:
        logger.error(f"Failed network agent analysis: {e}")
        findings = DomainAgentFinding(
            incident_type="networking",
            analysis="Failed to execute LLM analysis on network logs.",
            discovered_issues=["Network diagnostic query failed"],
            suggested_actions=["Check security groups manually"],
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "network_agent", 
            "completed",
            message=f"Network Agent analysis complete. Discovered: {findings.discovered_issues}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    # Store in domain_findings dict
    domain_findings = state.get("domain_findings") or {}
    domain_findings["network_agent"] = findings
    
    return {
        "domain_findings": domain_findings
    }

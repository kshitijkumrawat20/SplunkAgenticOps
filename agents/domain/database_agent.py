import os
import logging
import json
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import DomainAgentFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.database_agent")

async def database_agent_node(state: IncidentState) -> Dict[str, Any]:
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "database_agent", 
            "running",
            message="Database Agent executing domain-specific database diagnostics...",
            tools=["splunk_run_query"]
        )
        
    logger.info("Starting Database Agent...")
    
    # Query Splunk for database-related logs
    index = state.get("index", "opspilot_logs")
    query = f"search index={index} (DB OR database OR connection OR sql OR postgres OR pg_stat)"
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    
    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=15)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Database Agent query failed: {e}")
        
    log_lines = [r.get("_raw", "") for r in raw_results if r.get("_raw", "")]
    if not log_lines:
        log_lines = ["No database-related logs found in Splunk."]
        
    prompt = f"""
    You are the Database Agent of OpsPilot AI. Analyze the following telemetry logs:
    
    Logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Perform domain-specific database diagnostics.
    2. Identify database problems, query performance issues, or connection limits.
    3. Suggest remediation actions (e.g. scale replica, clear cache, optimize indexes).
    
    Provide your diagnostics in a DomainAgentFinding structure.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    db_llm = llm.with_structured_output(DomainAgentFinding)
    
    try:
        findings = db_llm.invoke(prompt)
    except Exception as e:
        logger.error(f"Failed database agent analysis: {e}")
        findings = DomainAgentFinding(
            incident_type="database",
            analysis="Failed to execute LLM analysis on database logs.",
            discovered_issues=["Database diagnostic query failed"],
            suggested_actions=["Verify DB connectivity manually"],
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "database_agent", 
            "completed",
            message=f"Database Agent analysis complete. Discovered: {findings.discovered_issues}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    # Store in domain_findings dict
    domain_findings = state.get("domain_findings") or {}
    domain_findings["database_agent"] = findings
    
    return {
        "domain_findings": domain_findings
    }

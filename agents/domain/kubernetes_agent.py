import os
import logging
import json
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import DomainAgentFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.kubernetes_agent")

async def kubernetes_agent_node(state: IncidentState) -> Dict[str, Any]:
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "kubernetes_agent", 
            "running",
            message="Kubernetes Agent executing domain-specific cluster diagnostics...",
            tools=["splunk_run_query"]
        )
        
    logger.info("Starting Kubernetes Agent...")
    
    # Query Splunk for kubernetes-related logs
    index = state.get("index", "opspilot_logs")
    query = f"search index={index} (pod OR kube OR kubernetes OR namespace OR oom OR restart OR container OR deployment)"
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    
    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=15)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Kubernetes Agent query failed: {e}")
        
    log_lines = [r.get("_raw", "") for r in raw_results if r.get("_raw", "")]
    if not log_lines:
        log_lines = ["No kubernetes-related logs found in Splunk."]
        
    prompt = f"""
    You are the Kubernetes Agent of OpsPilot AI. Analyze the following telemetry logs:
    
    Logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Perform kubernetes pod scheduler, event logs, and container state diagnostics.
    2. Identify pod restarts, CrashLoopBackOff states, container OOM kills, or deployment replica issues.
    3. Suggest kubernetes remediation actions (e.g. adjust pod resource request limits, restart deployment, scale replicas).
    
    Provide your diagnostics in a DomainAgentFinding structure.
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    k8s_llm = llm.with_structured_output(DomainAgentFinding)
    
    try:
        findings = k8s_llm.invoke(prompt)
    except Exception as e:
        logger.error(f"Failed kubernetes agent analysis: {e}")
        findings = DomainAgentFinding(
            incident_type="kubernetes",
            analysis="Failed to execute LLM analysis on kubernetes logs.",
            discovered_issues=["Kubernetes diagnostic query failed"],
            suggested_actions=["Inspect pod logs using kubectl manually"],
            confidence=0.5
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "kubernetes_agent", 
            "completed",
            message=f"Kubernetes Agent analysis complete. Discovered: {findings.discovered_issues}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    # Store in domain_findings dict
    domain_findings = state.get("domain_findings") or {}
    domain_findings["kubernetes_agent"] = findings
    
    return {
        "domain_findings": domain_findings
    }

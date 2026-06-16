import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load env variables before importing langchain
load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from api.mcp_client import SplunkMCPClient
from runbooks.runbook_db import search_runbooks
from .state import IncidentState
from .models import (
    LogAgentFinding,
    MetricsAgentFinding,
    DeploymentAgentFinding,
    RunbookAgentFinding,
    RCAFinding,
    ResponseFinding
)

logger = logging.getLogger("opspilot.nodes")

# Load environment and initialize LLM
api_key = os.getenv("GEMINI_API_KEY")
llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",
    google_api_key=api_key,
    temperature=0.0
)

# Bind structured outputs
log_llm = llm.with_structured_output(LogAgentFinding)
metrics_llm = llm.with_structured_output(MetricsAgentFinding)
deploy_llm = llm.with_structured_output(DeploymentAgentFinding)
runbook_llm = llm.with_structured_output(RunbookAgentFinding)
rca_llm = llm.with_structured_output(RCAFinding)
response_llm = llm.with_structured_output(ResponseFinding)

async def log_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Log Agent Node: Queries Splunk via SplunkMCPClient,
    identifies dominant errors, affected services, and timestamp ranges.
    """
    incident_id = state.get("incident_id")
    index = state.get("index", "opspilot_logs")
    query = state.get("error_query", f"search index={index} ERROR")
    earliest = state.get("earliest_time", "-24h")
    latest = state.get("latest_time", "now")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "log_agent", 
            "running",
            message=f"Connecting to Splunk MCP server... Querying index '{index}' with query '{query}'...",
            tools=["splunk_run_query"]
        )
    logger.info("Starting Log Agent...")

    raw_results = []
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs(query, earliest, latest, row_limit=50)
            raw_results = res.get("results", [])
    except Exception as e:
        logger.error(f"Log Agent failed to query Splunk: {e}")
        # Fallback to empty results
        raw_results = []

    # Format raw logs for LLM
    log_lines = []
    for r in raw_results:
        raw_line = r.get("_raw", "")
        if raw_line:
            log_lines.append(raw_line)
            
    if not log_lines:
        # Fallback raw line if no Splunk results retrieved
        log_lines = ["No matching logs found in Splunk."]

    from config.environment import get_active_profile
    active_profile = get_active_profile()
    profile_dict = active_profile.to_dict()
    services_hint = ", ".join([f"'{s}'" for s in profile_dict['services']]) if profile_dict['services'] else "services/components"

    # Ask LLM to extract findings
    prompt = f"""
    You are the Log Agent of OpsPilot AI. Analyze the following raw log lines from index '{index}':
    
    Raw logs:
    {json.dumps(log_lines, indent=2)}
    
    Examine the logs to:
    1. Identify the dominant error messages.
    2. Extract affected services (look for patterns matching the active environment's services: {services_hint}).
    3. Determine the earliest and latest timestamp of these errors.
    4. Provide a sample of relevant raw logs.
    """
    
    findings = log_llm.invoke(prompt)
    
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "log_agent", 
            "completed",
            message=f"Analyzed {len(log_lines)} logs. Identified affected services: {findings.affected_services}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "log_findings": findings,
        "raw_logs": log_lines
    }

async def metrics_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Metrics Agent Node: Analyzes the volume of errors,
    detects spikes, and rates severity (1-10).
    """
    incident_id = state.get("incident_id")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "metrics_agent", 
            "running",
            message="Analyzing log error frequencies and rolling severity metrics..."
        )
    logger.info("Starting Metrics Agent...")
    raw_logs = state.get("raw_logs", [])
    
    prompt = f"""
    You are the Metrics Agent of OpsPilot AI. Analyze the volume of errors based on the following raw log lines:
    
    Raw logs count: {len(raw_logs)}
    Logs:
    {json.dumps(raw_logs[:20], indent=2)}
    
    Examine the count and content to:
    1. Count total error events in the window.
    2. Assess if there is a sudden spike (e.g. multiple identical errors within seconds).
    3. Generate a severity score from 1 (low) to 10 (critical).
    4. Provide volume analysis notes explaining the reasoning.
    """
    
    findings = metrics_llm.invoke(prompt)
    
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "metrics_agent", 
            "completed",
            message=f"Metrics analyzed. Severity: {findings.severity_score}/10, Spike detected: {findings.spike_detected}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "metrics_findings": findings
    }

async def deployment_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Deployment Agent Node: Reads local logs/deployment.log,
    correlates deployments with log errors.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "deployment_agent", 
            "running",
            message="Reading deployment logs to correlate releases with outage timeline...",
            tools=["splunk_get_deployments"]
        )
    logger.info("Starting Deployment Agent...")
    log_findings = state.get("log_findings")
    if isinstance(log_findings, dict):
        affected_services = log_findings.get("affected_services") or []
    else:
        affected_services = getattr(log_findings, "affected_services", []) if log_findings else []
    
    # Read local deployment logs
    deploy_content = ""
    deploy_log_path = "./logs/deployment.log"
    if os.path.exists(deploy_log_path):
        with open(deploy_log_path, "r", encoding="utf-8") as f:
            deploy_content = f.read()
    else:
        deploy_content = "No deployment.log file found."

    prompt = f"""
    You are the Deployment Agent of OpsPilot AI. Correlate recent deployments with the current incident.
    
    Affected services from Log Agent: {affected_services}
    
    Deployment Log Contents:
    {deploy_content}
    
    Analyze the deployment timestamps and compare them with the incident timeline to:
    1. Identify any deployments correlated with the incident.
    2. Note if a recent deployment is highly suspicious (e.g., deployed just before the errors started).
    3. Explain the correlation in detail.
    """
    
    findings = deploy_llm.invoke(prompt)
    
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "deployment_agent", 
            "completed",
            message=f"Deployments checked. Correlated: {findings.deployments_correlated}, Suspicious change: {findings.is_suspicious_change}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "deployment_findings": findings
    }

async def runbook_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Runbook Agent Node: Searches local runbooks recursively,
    filters by plan category and dominant errors, ranks relevance,
    and returns synthesized proposed remediations.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "runbook_agent", 
            "running",
            message="Scanning local playbooks and ranking relevance to dynamic plan context..."
        )
    logger.info("Starting Runbook Agent...")
    log_findings = state.get("log_findings")
    if isinstance(log_findings, dict):
        dominant_errors = log_findings.get("dominant_errors") or []
    else:
        dominant_errors = getattr(log_findings, "dominant_errors", []) if log_findings else []
    
    plan = state.get("investigation_plan")
    if isinstance(plan, dict):
        category = plan.get("incident_type", "unknown")
    else:
        category = getattr(plan, "incident_type", "unknown") if plan else "unknown"
    
    # Search local runbook DB using errors and incident category
    remediations_raw = []
    runbook_names = set()
    
    search_queries = list(dominant_errors) + [category]
    for q in search_queries:
        matches = search_runbooks(q)
        for m in matches:
            if m["runbook"] not in runbook_names:
                runbook_names.add(m["runbook"])
                remediations_raw.append(f"File: {m['runbook']}\nContent:\n{m['content']}")
            
    # Format runbook matches for LLM
    runbook_data = "\n\n---\n\n".join(remediations_raw) if remediations_raw else "No runbooks found matching criteria."

    prompt = f"""
    You are the Runbook Discovery and Relevance Agent of OpsPilot AI.
    Your goal is to analyze the discovered runbook sections, rate their relevance to the current category '{category}' and errors, and compile the best fixes.
    
    Incident Category: {category}
    Dominant errors found: {dominant_errors}
    
    Matching Runbook Files and Content:
    {runbook_data}
    
    Please synthesize the findings:
    1. Filter out runbooks that are not relevant to the incident category and errors.
    2. Rank the remaining ones and extract matching_runbooks.
    3. Generate the final proposed_remediations list of actionable instructions.
    """
    
    findings = runbook_llm.invoke(prompt)
    
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "runbook_agent", 
            "completed",
            message=f"Runbooks matched: {findings.matching_runbooks}. Proposed fixes: {findings.proposed_remediations}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "runbook_findings": findings
    }

async def rca_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    RCA Agent Node: Synthesizes findings from log, metrics, deployment,
    runbook, and historical context to generate a root cause hypothesis.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "rca_agent", 
            "running",
            message="Synthesizing all collected findings to formulate root cause hypothesis..."
        )
    logger.info("Starting RCA Agent...")
    log = state.get("log_findings")
    metrics = state.get("metrics_findings")
    deploy = state.get("deployment_findings")
    runbook = state.get("runbook_findings")
    historical = state.get("historical_context")

    anomaly = state.get("anomaly_findings")

    def get_val(obj, key, default=None):
        if not obj:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def serialize_finding(f):
        if not f:
            return 'None'
        if hasattr(f, 'model_dump_json'):
            return f.model_dump_json()
        import json
        return json.dumps(f, indent=2)

    anomaly_str = ""
    if anomaly:
        anomaly_str = f"""
        Anomaly Detection Findings:
        Anomaly Detected: {get_val(anomaly, 'anomaly_detected', False)}
        Anomaly Type: {get_val(anomaly, 'anomaly_type', 'none')}
        Confidence: {get_val(anomaly, 'confidence', 0.0)}
        Affected Service: {get_val(anomaly, 'affected_service', 'Unknown')}
        Description: {get_val(anomaly, 'description', '')}
        """

    historical_str = ""
    if historical:
        historical_str = f"""
        Historical Incident Context:
        Similar Incidents Found: {historical.get('similar_incidents_found', 0)}
        Recommended Fix from History: {historical.get('recommended_fix', 'None')}
        Historical Success Rate of this Fix: {historical.get('historical_success_rate', 1.0)}
        """

    prompt = f"""
    You are the Root Cause Analysis (RCA) Agent of OpsPilot AI. Combine all agent findings and form a hypothesis.
    
    Log Findings:
    {serialize_finding(log)}
    
    Metrics Findings:
    {serialize_finding(metrics)}
    
    {anomaly_str}
    
    Deployment Findings:
    {serialize_finding(deploy)}
    
    Runbook Findings:
    {serialize_finding(runbook)}
    
    {historical_str}
    
    Examine the evidence to:
    1. Formulate a root cause hypothesis.
    2. Provide a confidence score (between 0.0 and 1.0).
    3. Synthesize the combined evidence supporting this hypothesis.
    """
    
    findings = rca_llm.invoke(prompt)
    
    # Append event to timeline
    timeline = state.get("timeline") or []
    timeline.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": "rca",
        "description": f"Root cause identified: {findings.root_cause_hypothesis}"
    })
    
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "rca_agent", 
            "completed",
            message=f"RCA complete. Hypothesis: '{findings.root_cause_hypothesis}' (Confidence: {int(findings.confidence_score*100)}%)",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "rca_findings": findings,
        "timeline": timeline
    }

async def response_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Response Agent Node: Generates remediation steps and an executive summary,
    saves the final report and historical incident records.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "response_agent", 
            "running",
            message="Generating final step-by-step commands and leadership briefing..."
        )
    logger.info("Starting Response Agent...")
    rca = state.get("rca_findings")
    runbook = state.get("runbook_findings")

    def serialize_finding(f):
        if not f:
            return 'None'
        if hasattr(f, 'model_dump_json'):
            return f.model_dump_json()
        import json
        return json.dumps(f, indent=2)

    prompt = f"""
    You are the Response Agent of OpsPilot AI. Generate remediation recommendations and an executive summary.
    
    Root Cause Analysis:
    {serialize_finding(rca)}
    
    Runbook Remediations:
    {serialize_finding(runbook)}
    
    Extract and generate:
    1. Step-by-step remediation steps (actual commands or processes).
    2. An executive business-level summary of the outage and repair action.
    """
    
    findings = response_llm.invoke(prompt)
    
    # Generate executive summary briefing using Gemini Executive Summary Agent
    from agents.executive_summary_agent import generate_executive_briefing
    briefing = generate_executive_briefing(state)
    
    # Process timeline
    timeline = state.get("timeline") or []
    try:
        timeline.sort(key=lambda x: x.get("timestamp", ""))
    except Exception as e:
        logger.warning(f"Failed to sort timeline events: {e}")
        
    # Write timeline.json
    os.makedirs("reports", exist_ok=True)
    timeline_path = "reports/timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump({"events": timeline}, f, indent=2)
        
    # Save incident to historical database
    from memory.incident_store import save_incident
    log_find = state.get("log_findings")
    affected_service = "Unknown"
    if log_find:
        if hasattr(log_find, "affected_services") and log_find.affected_services:
            affected_service = log_find.affected_services[0]
        elif isinstance(log_find, dict) and log_find.get("affected_services"):
            affected_service = log_find["affected_services"][0]
            
    root_cause = rca.root_cause_hypothesis if rca else "Unknown"
    remediation_steps = findings.remediation_steps if findings else []
    
    # Determine approval status for success field
    approved = False
    approval_status = state.get("approval_status")
    if approval_status:
        approved = approval_status.get("approved", False)
    
    classification = state.get("classification_findings")
    if isinstance(classification, dict):
        incident_type = classification.get("incident_type", "unknown")
    else:
        incident_type = getattr(classification, "incident_type", "unknown") if classification else "unknown"
        
    from config.environment import get_active_profile
    active_profile = get_active_profile()
    industry = active_profile.environment_type

    plan = state.get("investigation_plan")
    plan_dict = plan.model_dump() if plan and hasattr(plan, "model_dump") else plan
    
    domain_finds = state.get("domain_findings") or {}
    domain_finds_serialized = {}
    for k, v in domain_finds.items():
        domain_finds_serialized[k] = v.model_dump() if hasattr(v, "model_dump") else v

    save_incident({
        "incident_id": incident_id,
        "root_cause": root_cause,
        "affected_service": affected_service,
        "incident_type": incident_type,
        "industry": industry,
        "investigation_plan": plan_dict,
        "domain_findings": domain_finds_serialized,
        "remediation": remediation_steps,
        "success": approved,
        "approved": approved,
        "executive_summary": briefing,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "root_cause_analysis": {
            "hypothesis": briefing,
            "rca_hypothesis": rca.root_cause_hypothesis if rca else "Unknown",
            "confidence_score": rca.confidence_score if rca else 0.0,
            "evidence": rca.evidence if rca else "No evidence collected"
        },
        "timeline": timeline,
        "historical_context": state.get("historical_context") or {}
    })
    
    def get_val(obj, key, default=None):
        if not obj:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    # Compile the final incident report JSON
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "incident_name": state.get("alert_name", "OpsPilot Incident"),
        "executive_summary": briefing,
        "incident_type": incident_type,
        "industry": industry,
        "investigation_plan": plan_dict,
        "domain_findings": domain_finds_serialized,
        "logs": {
            "query": state.get("error_query"),
            "dominant_errors": get_val(state.get("log_findings"), 'dominant_errors', []),
            "affected_services": get_val(state.get("log_findings"), 'affected_services', [])
        },
        "metrics": {
            "error_count": get_val(state.get("metrics_findings"), 'error_count', 0),
            "spike_detected": get_val(state.get("metrics_findings"), 'spike_detected', False),
            "severity_score": get_val(state.get("metrics_findings"), 'severity_score', 1)
        },
        "anomaly": {
            "anomaly_detected": get_val(state.get("anomaly_findings"), 'anomaly_detected', False),
            "anomaly_type": get_val(state.get("anomaly_findings"), 'anomaly_type', 'none'),
            "confidence": get_val(state.get("anomaly_findings"), 'confidence', 0.0),
            "affected_service": get_val(state.get("anomaly_findings"), 'affected_service', 'Unknown'),
            "description": get_val(state.get("anomaly_findings"), 'description', 'No anomaly findings')
        },
        "deployments": {
            "correlated": get_val(state.get("deployment_findings"), 'deployments_correlated', []),
            "suspicious": get_val(state.get("deployment_findings"), 'is_suspicious_change', False)
        },
        "runbooks": {
            "matched": get_val(state.get("runbook_findings"), 'matching_runbooks', [])
        },
        "root_cause_analysis": {
            "hypothesis": briefing,  # Executive summary briefing as main description
            "rca_hypothesis": rca.root_cause_hypothesis if rca else "Unknown",
            "confidence_score": rca.confidence_score if rca else 0.0,
            "evidence": rca.evidence if rca else "No evidence collected"
        },
        # Phase 2 Enhancements
        "timeline": {"events": timeline},
        "historical_context": state.get("historical_context") or {},
        "root_cause": {
            "rca_hypothesis": rca.root_cause_hypothesis if rca else "Unknown",
            "confidence_score": rca.confidence_score if rca else 0.0,
            "evidence": rca.evidence if rca else "No evidence collected"
        },
        "remediation": {
            "steps": remediation_steps,
            "executive_summary": briefing
        }
    }
    
    # Save the report to reports/incident_report.json
    report_path = "reports/incident_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        
    logger.info(f"Incident report saved successfully to {report_path}")
    
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "response_agent", 
            "completed",
            message="Incident response complete. Summary briefing published.",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "response_findings": findings
    }

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
    affected_services = log_findings.affected_services if log_findings else []
    
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
    Runbook Agent Node: Searches local runbooks/*.md for keywords,
    retrieves proposed remediations.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        from api.websocket_manager import manager
        await manager.send_status(
            incident_id, 
            "runbook_agent", 
            "running",
            message="Scanning local knowledge base and runbooks directory for matches..."
        )
    logger.info("Starting Runbook Agent...")
    log_findings = state.get("log_findings")
    dominant_errors = log_findings.dominant_errors if log_findings else []
    
    # Search local runbook DB
    remediations_raw = []
    runbook_names = []
    for err in dominant_errors:
        matches = search_runbooks(err)
        for m in matches:
            runbook_names.append(m["runbook"])
            remediations_raw.append(m["content"])
            
    # Format runbook matches for LLM
    runbook_data = "\n\n".join(remediations_raw) if remediations_raw else "No runbooks found for these errors."

    prompt = f"""
    You are the Runbook Agent of OpsPilot AI. Retrieve possible fixes and remediations.
    
    Dominant errors found: {dominant_errors}
    
    Matching Runbook Files/Content:
    {runbook_data}
    
    Synthesize findings to:
    1. List the matched runbooks.
    2. Present proposed remediations and actionable steps in a clean list format.
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

    anomaly_str = ""
    if anomaly:
        anomaly_str = f"""
        Anomaly Detection Findings:
        Anomaly Detected: {anomaly.anomaly_detected}
        Anomaly Type: {anomaly.anomaly_type}
        Confidence: {anomaly.confidence}
        Affected Service: {anomaly.affected_service}
        Description: {anomaly.description}
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
    {log.model_dump_json() if log else 'None'}
    
    Metrics Findings:
    {metrics.model_dump_json() if metrics else 'None'}
    
    {anomaly_str}
    
    Deployment Findings:
    {deploy.model_dump_json() if deploy else 'None'}
    
    Runbook Findings:
    {runbook.model_dump_json() if runbook else 'None'}
    
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

    prompt = f"""
    You are the Response Agent of OpsPilot AI. Generate remediation recommendations and an executive summary.
    
    Root Cause Analysis:
    {rca.model_dump_json() if rca else 'None'}
    
    Runbook Remediations:
    {runbook.model_dump_json() if runbook else 'None'}
    
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
    incident_type = classification.incident_type if classification else "unknown"
    from config.environment import get_active_profile
    active_profile = get_active_profile()
    industry = active_profile.environment_type

    save_incident({
        "incident_id": incident_id,
        "root_cause": root_cause,
        "affected_service": affected_service,
        "incident_type": incident_type,
        "industry": industry,
        "remediation": remediation_steps,
        "success": approved,
        "approved": approved,
        "executive_summary": briefing,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })
    
    # Compile the final incident report JSON
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "incident_name": state.get("alert_name", "OpsPilot Incident"),
        "executive_summary": briefing,
        "incident_type": incident_type,
        "industry": industry,
        "logs": {
            "query": state.get("error_query"),
            "dominant_errors": state.get("log_findings").dominant_errors if state.get("log_findings") else [],
            "affected_services": state.get("log_findings").affected_services if state.get("log_findings") else []
        },
        "metrics": {
            "error_count": state.get("metrics_findings").error_count if state.get("metrics_findings") else 0,
            "spike_detected": state.get("metrics_findings").spike_detected if state.get("metrics_findings") else False,
            "severity_score": state.get("metrics_findings").severity_score if state.get("metrics_findings") else 1
        },
        "anomaly": {
            "anomaly_detected": state.get("anomaly_findings").anomaly_detected if state.get("anomaly_findings") else False,
            "anomaly_type": state.get("anomaly_findings").anomaly_type if state.get("anomaly_findings") else "none",
            "confidence": state.get("anomaly_findings").confidence if state.get("anomaly_findings") else 0.0,
            "affected_service": state.get("anomaly_findings").affected_service if state.get("anomaly_findings") else "Unknown",
            "description": state.get("anomaly_findings").description if state.get("anomaly_findings") else "No anomaly findings"
        },
        "deployments": {
            "correlated": state.get("deployment_findings").deployments_correlated if state.get("deployment_findings") else [],
            "suspicious": state.get("deployment_findings").is_suspicious_change if state.get("deployment_findings") else False
        },
        "runbooks": {
            "matched": state.get("runbook_findings").matching_runbooks if state.get("runbook_findings") else []
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

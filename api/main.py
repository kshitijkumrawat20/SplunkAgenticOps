import os
import uuid
import logging
from datetime import datetime
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("opspilot.main")

from agents import graph
from api.mcp_client import SplunkMCPClient

def dump_finding(val: Any) -> Any:
    if val is None:
        return None
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if hasattr(val, "dict"):
        return val.dict()
    if isinstance(val, dict):
        return {k: dump_finding(v) for k, v in val.items()}
    if isinstance(val, list):
        return [dump_finding(v) for v in val]
    return val

app = FastAPI(
    title="OpsPilot AI — Autonomous Incident Investigation & Response Platform",
    version="1.0.0",
    description="Multi-agent platform for automated Splunk incident response and RCA."
)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class InvestigationRequest(BaseModel):
    incident_id: Optional[str] = Field(None, description="Unique incident/investigation ID. Generated if not supplied.")
    alert_name: str = Field(default="Manual Investigation", description="Name of the alert/incident")
    index: str = Field(default="opspilot_logs", description="Splunk index to search")
    error_query: str = Field(default="search index=opspilot_logs ERROR", description="SPL query to execute")
    earliest_time: str = Field(default="-24h", description="Earliest search boundary (e.g. -24h)")
    latest_time: str = Field(default="now", description="Latest search boundary (e.g. now)")

class WebhookRequest(BaseModel):
    # Standard Splunk Webhook payload schema
    sid: Optional[str] = Field(None, description="Search ID")
    search_name: str = Field(description="Saved search / Alert name")
    app: Optional[str] = Field(None, description="Splunk App context")
    owner: Optional[str] = Field(None, description="Owner of the search")
    results_link: Optional[str] = Field(None, description="Link to search results")
    result: Optional[dict] = Field(None, description="Raw result dictionary from the triggered alert")

class ApprovalRequest(BaseModel):
    incident_id: str = Field(description="Incident ID to approve or reject")
    approved: bool = Field(description="Set to true to approve remediation, false to reject")

class ProfileSelectRequest(BaseModel):
    profile: str = Field(description="Name of the environment profile to select")

@app.get("/profiles")
async def get_profiles():
    """
    Returns available environment profiles and the currently active profile name.
    """
    from config.environment import get_available_profiles, get_active_profile_name
    return {
        "available_profiles": get_available_profiles(),
        "active_profile": get_active_profile_name()
    }

@app.post("/profiles/select")
async def select_profile(req: ProfileSelectRequest):
    """
    Switches the active environment profile.
    """
    from config.environment import set_active_profile_name
    success = set_active_profile_name(req.profile)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set active profile to '{req.profile}'. Profile not found or error writing config.")
    return {
        "status": "success",
        "active_profile": req.profile
    }

@app.get("/health")
async def health_check():
    """Health check endpoint. Verifies Splunk connectivity."""
    splunk_connected = False
    error_message = None
    try:
        async with SplunkMCPClient() as client:
            res = await client.search_logs("search index=opspilot_logs | head 1", earliest_time="-5m", latest_time="now")
            if "results" in res:
                splunk_connected = True
    except Exception as e:
        error_message = str(e)
        logger.error(f"Health check failed to connect to Splunk: {e}")

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "splunk_mcp_connected": splunk_connected,
        "splunk_mcp_error": error_message
    }

@app.post("/investigate")
async def run_investigation(req: InvestigationRequest):
    """
    Synchronously triggers the LangGraph investigation workflow on demand
    and returns the compiled root cause analysis and recommendations.
    """
    incident_id = req.incident_id or str(uuid.uuid4())
    logger.info(f"Received manual investigation request for alert: {req.alert_name} (ID: {incident_id})")
    inputs = {
        "incident_id": incident_id,
        "alert_name": req.alert_name,
        "index": req.index,
        "error_query": req.error_query,
        "earliest_time": req.earliest_time,
        "latest_time": req.latest_time
    }
    
    try:
        # Invoke LangGraph using a checkpoint checkpointer thread config
        config = {"configurable": {"thread_id": incident_id}}
        await graph.ainvoke(inputs, config=config)
        
        # Retrieve state from checkpoint since graph paused before approval_node
        state = await graph.aget_state(config)
        
        if "approval_node" in state.next:
            return {
                "status": "pending_approval",
                "incident_id": incident_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "remediation_proposal": dump_finding(state.values.get("remediation_proposal")),
                "findings": {
                    "investigation_plan": dump_finding(state.values.get("investigation_plan")),
                    "domain_findings": dump_finding(state.values.get("domain_findings")),
                    "classification_findings": dump_finding(state.values.get("classification_findings")),
                    "log_findings": dump_finding(state.values.get("log_findings")),
                    "metrics_findings": dump_finding(state.values.get("metrics_findings")),
                    "anomaly_findings": dump_finding(state.values.get("anomaly_findings")),
                    "deployment_findings": dump_finding(state.values.get("deployment_findings")),
                    "runbook_findings": dump_finding(state.values.get("runbook_findings")),
                    "rca_findings": dump_finding(state.values.get("rca_findings"))
                }
            }
            
        # If execution ran to the end without breakpoint (fallback)
        return {
            "status": "completed",
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "findings": {
                "investigation_plan": dump_finding(state.values.get("investigation_plan")),
                "domain_findings": dump_finding(state.values.get("domain_findings")),
                "classification_findings": dump_finding(state.values.get("classification_findings")),
                "log_findings": dump_finding(state.values.get("log_findings")),
                "metrics_findings": dump_finding(state.values.get("metrics_findings")),
                "anomaly_findings": dump_finding(state.values.get("anomaly_findings")),
                "deployment_findings": dump_finding(state.values.get("deployment_findings")),
                "runbook_findings": dump_finding(state.values.get("runbook_findings")),
                "rca_findings": dump_finding(state.values.get("rca_findings")),
                "remediation_proposal": dump_finding(state.values.get("remediation_proposal")),
                "response_findings": dump_finding(state.values.get("response_findings"))
            }
        }
    except Exception as e:
        logger.error(f"Investigation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Investigation execution failed: {str(e)}")

@app.post("/approve")
async def approve_remediation(req: ApprovalRequest):
    """
    Approves/rejects the pending remediation proposal and resumes execution.
    """
    logger.info(f"Received approval request for incident: {req.incident_id}. Approved: {req.approved}")
    config = {"configurable": {"thread_id": req.incident_id}}
    state = await graph.aget_state(config)
    
    if not state or not state.next:
        raise HTTPException(status_code=404, detail="Incident not found or already completed.")
        
    if "approval_node" not in state.next:
        raise HTTPException(status_code=400, detail=f"Incident is not in approval state. Current state: {state.next}")
        
    proposal = state.values.get("remediation_proposal")
    
    # Format approval_status payload
    approval_payload = {
        "approved": req.approved,
        "action": dump_finding(proposal)
    }
    
    # Update thread state with the approval status
    await graph.aupdate_state(
        config,
        {"approval_status": approval_payload}
    )
    
    # Resume graph execution (invoking with None will resume from breakpoint)
    try:
        final_state = await graph.ainvoke(None, config=config)
        
        return {
            "status": "completed" if req.approved else "rejected",
            "incident_id": req.incident_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "findings": {
                "investigation_plan": dump_finding(final_state.get("investigation_plan")),
                "domain_findings": dump_finding(final_state.get("domain_findings")),
                "classification_findings": dump_finding(final_state.get("classification_findings")),
                "log_findings": dump_finding(final_state.get("log_findings")),
                "metrics_findings": dump_finding(final_state.get("metrics_findings")),
                "anomaly_findings": dump_finding(final_state.get("anomaly_findings")),
                "deployment_findings": dump_finding(final_state.get("deployment_findings")),
                "runbook_findings": dump_finding(final_state.get("runbook_findings")),
                "rca_findings": dump_finding(final_state.get("rca_findings")),
                "remediation_proposal": dump_finding(final_state.get("remediation_proposal")),
                "response_findings": dump_finding(final_state.get("response_findings"))
            }
        }
    except Exception as e:
        logger.error(f"Failed to resume graph execution: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume execution: {str(e)}")

async def run_background_investigation(incident_id: str, search_name: str, index: str, query: str):
    inputs = {
        "incident_id": incident_id,
        "alert_name": search_name,
        "index": index,
        "error_query": query,
        "earliest_time": "-24h",
        "latest_time": "now"
    }
    try:
        logger.info(f"Running background investigation for webhook: {search_name} (ID: {incident_id})")
        config = {"configurable": {"thread_id": incident_id}}
        await graph.ainvoke(inputs, config=config)
    except Exception as e:
        logger.error(f"Background investigation failed for alert {search_name}: {e}")

@app.post("/alerts")
async def receive_alert(webhook: WebhookRequest, background_tasks: BackgroundTasks):
    """
    Receives webhook alerts from Splunk. Triggers the LangGraph
    investigation workflow in the background.
    """
    incident_id = str(uuid.uuid4())
    logger.info(f"Received Splunk Alert Webhook: {webhook.search_name} (ID: {incident_id})")
    
    # Extract index and query from alert info if possible, otherwise use defaults
    index = "opspilot_logs"
    query = "search index=opspilot_logs ERROR"
    
    # If Splunk webhook contains the result event details, extract it
    if webhook.result:
        index = webhook.result.get("index", index)
        # Reconstruct query or use standard search
        query = f"search index={index} ERROR"

    # Enqueue investigation in the background
    background_tasks.add_task(
        run_background_investigation,
        incident_id,
        webhook.search_name,
        index,
        query
    )
    
    return {
        "status": "alert_received",
        "message": "Autonomous multi-agent investigation triggered in the background.",
        "incident_name": webhook.search_name,
        "incident_id": incident_id
    }

@app.websocket("/ws/investigation/{incident_id}")
async def websocket_endpoint(websocket: WebSocket, incident_id: str):
    """
    WebSocket endpoint to stream live multi-agent investigation status updates.
    """
    from api.websocket_manager import manager
    
    await manager.connect(websocket, incident_id)
    try:
        while True:
            # Keep socket alive; wait for messages or client disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket, incident_id)
    except Exception as e:
        logger.error(f"WebSocket connection error on incident {incident_id}: {e}")
        await manager.disconnect(websocket, incident_id)

@app.get("/incidents")
async def get_incidents_endpoint():
    """
    Returns all stored incidents from historical memory.
    """
    from memory.incident_store import get_all_incidents
    return get_all_incidents()

@app.get("/incidents/{incident_id}")
async def get_incident_by_id_endpoint(incident_id: str):
    """
    Returns a specific incident by ID.
    """
    from memory.incident_store import get_incident_by_id
    incident = get_incident_by_id(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident with ID {incident_id} not found.")
    return incident

@app.get("/incidents/similar/{service_name}")
async def get_similar_incidents_endpoint(service_name: str):
    """
    Returns historical incidents matching the service name.
    """
    from memory.incident_store import search_incident_history
    return search_incident_history(service_name)

@app.get("/dashboard/summary")
async def get_dashboard_summary():
    """
    Returns summary statistics for the dashboard, including:
    - active_count: count of active investigations
    - resolved_count: count of completed investigations in database
    - top_root_causes: frequency map of root causes
    - approval_rate: percentage of approved vs rejected incidents
    """
    from memory.incident_store import get_all_incidents
    incidents = get_all_incidents()
    
    # Active incidents from checkpointer
    configs = list(graph.checkpointer.list(config=None))
    active_count = 0
    seen_threads = set()
    for c in configs:
        thread_id = c.config.get("configurable", {}).get("thread_id")
        if not thread_id or thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        state = await graph.aget_state(c.config)
        if state.next:
            active_count += 1
            
    resolved_count = len(incidents)
    
    # Top root causes and approval stats
    root_causes = {}
    total_approved = 0
    total_with_approval_decision = 0
    for inc in incidents:
        rc = inc.get("root_cause", "Unknown")
        root_causes[rc] = root_causes.get(rc, 0) + 1
        
        # Check approval status
        if "approved" in inc:
            total_with_approval_decision += 1
            if inc["approved"]:
                total_approved += 1
        else:
            if inc.get("success", False):
                total_approved += 1
            total_with_approval_decision += 1
            
    approval_rate = 100.0
    if total_with_approval_decision > 0:
        approval_rate = round((total_approved / total_with_approval_decision) * 100, 2)
        
    sorted_rc = dict(sorted(root_causes.items(), key=lambda x: x[1], reverse=True)[:5])
    
    return {
        "active_count": active_count,
        "resolved_count": resolved_count,
        "top_root_causes": sorted_rc,
        "approval_rate": approval_rate
    }

@app.get("/dashboard/live")
async def get_dashboard_live():
    """
    Lists active investigations currently executing or paused for approval.
    """
    configs = list(graph.checkpointer.list(config=None))
    live_incidents = []
    seen_threads = set()
    for c in configs:
        thread_id = c.config.get("configurable", {}).get("thread_id")
        if not thread_id or thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        
        state = await graph.aget_state(c.config)
        if state.next:
            status = "pending_approval" if "approval_node" in state.next else "running"
            
            vals = state.values
            affected_service = "Unknown"
            log_find = vals.get("log_findings")
            if log_find:
                if hasattr(log_find, "affected_services") and log_find.affected_services:
                    affected_service = log_find.affected_services[0]
                elif isinstance(log_find, dict) and log_find.get("affected_services"):
                    affected_service = log_find["affected_services"][0]
            
            # Formulate proposal structure if pending approval
            remediation_proposal = None
            proposal = vals.get("remediation_proposal")
            if proposal:
                remediation_proposal = dump_finding(proposal)
                
            live_incidents.append({
                "incident_id": thread_id,
                "incident_name": vals.get("alert_name", "OpsPilot Incident"),
                "status": status,
                "affected_service": affected_service,
                "remediation_proposal": remediation_proposal,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
    return live_incidents

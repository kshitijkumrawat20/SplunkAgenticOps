import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("opspilot.main")

from agents import graph
from api.mcp_client import SplunkMCPClient

app = FastAPI(
    title="OpsPilot AI — Autonomous Incident Investigation & Response Platform",
    version="1.0.0",
    description="Multi-agent platform for automated Splunk incident response and RCA."
)

class InvestigationRequest(BaseModel):
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
    logger.info(f"Received manual investigation request for alert: {req.alert_name}")
    inputs = {
        "alert_name": req.alert_name,
        "index": req.index,
        "error_query": req.error_query,
        "earliest_time": req.earliest_time,
        "latest_time": req.latest_time
    }
    
    try:
        # Invoke LangGraph
        result = await graph.ainvoke(inputs)
        
        # Extract findings from state
        return {
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "findings": {
                "log_findings": result.get("log_findings"),
                "metrics_findings": result.get("metrics_findings"),
                "deployment_findings": result.get("deployment_findings"),
                "runbook_findings": result.get("runbook_findings"),
                "rca_findings": result.get("rca_findings"),
                "response_findings": result.get("response_findings")
            }
        }
    except Exception as e:
        logger.error(f"Investigation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Investigation execution failed: {str(e)}")

async def run_background_investigation(search_name: str, index: str, query: str):
    inputs = {
        "alert_name": search_name,
        "index": index,
        "error_query": query,
        "earliest_time": "-24h",
        "latest_time": "now"
    }
    try:
        logger.info(f"Running background investigation for webhook: {search_name}")
        await graph.ainvoke(inputs)
    except Exception as e:
        logger.error(f"Background investigation failed for alert {search_name}: {e}")

@app.post("/alerts")
async def receive_alert(webhook: WebhookRequest, background_tasks: BackgroundTasks):
    """
    Receives webhook alerts from Splunk. Triggers the LangGraph
    investigation workflow in the background.
    """
    logger.info(f"Received Splunk Alert Webhook: {webhook.search_name}")
    
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
        webhook.search_name,
        index,
        query
    )
    
    return {
        "status": "alert_received",
        "message": "Autonomous multi-agent investigation triggered in the background.",
        "incident_name": webhook.search_name
    }

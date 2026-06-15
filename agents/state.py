from typing import Dict, Any, Optional, TypedDict
from .models import (
    LogAgentFinding,
    MetricsAgentFinding,
    DeploymentAgentFinding,
    RunbookAgentFinding,
    RCAFinding,
    ResponseFinding
)

class IncidentState(TypedDict):
    # Inputs
    alert_name: str
    index: str
    error_query: str
    earliest_time: str
    latest_time: str
    
    # Raw data pulled from Splunk (temporary storage if needed)
    raw_logs: Optional[list]
    
    # Agent outputs
    log_findings: Optional[LogAgentFinding]
    metrics_findings: Optional[MetricsAgentFinding]
    deployment_findings: Optional[DeploymentAgentFinding]
    runbook_findings: Optional[RunbookAgentFinding]
    rca_findings: Optional[RCAFinding]
    response_findings: Optional[ResponseFinding]
    
    # Execution workflow tracking
    supervisor_next: Optional[str]

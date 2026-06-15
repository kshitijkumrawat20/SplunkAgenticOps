from typing import Dict, Any, Optional, TypedDict
from .models import (
    LogAgentFinding,
    MetricsAgentFinding,
    DeploymentAgentFinding,
    RunbookAgentFinding,
    RCAFinding,
    ResponseFinding,
    RemediationProposal,
    HistoricalContext,
    TimelineEvent,
    AnomalyFinding,
    ClassificationFinding
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
    classification_findings: Optional[ClassificationFinding]
    
    # Execution workflow tracking
    supervisor_next: Optional[str]

    # New fields for Remediation & Approval
    incident_id: Optional[str]
    remediation_proposal: Optional[RemediationProposal]
    approval_status: Optional[dict]

    # Phase 2 Timeline & Memory
    timeline: Optional[list]
    historical_context: Optional[dict]

    # Phase 3 Anomaly detection
    anomaly_findings: Optional[AnomalyFinding]

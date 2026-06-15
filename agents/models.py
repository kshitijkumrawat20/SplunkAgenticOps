from pydantic import BaseModel, Field
from typing import List, Optional

class LogAgentFinding(BaseModel):
    dominant_errors: List[str] = Field(description="List of primary/dominant error messages found in logs")
    affected_services: List[str] = Field(description="Services impacted by these errors (e.g. order-service)")
    earliest_timestamp: str = Field(description="Earliest timestamp of the matching errors")
    latest_timestamp: str = Field(description="Latest timestamp of the matching errors")
    sample_raw_logs: List[str] = Field(description="List of raw log sample lines for evidence")

class MetricsAgentFinding(BaseModel):
    error_count: int = Field(description="Total count of error events in the analyzed window")
    spike_detected: bool = Field(description="True if there is a sudden spike or abnormal volume increase")
    severity_score: int = Field(description="Incident severity score from 1 (low) to 10 (critical)")
    volume_analysis_notes: str = Field(description="Brief explanation of the error volume behavior")

class DeploymentAgentFinding(BaseModel):
    deployments_correlated: List[str] = Field(description="List of recent deployments that correlate with the incident timeline")
    correlation_notes: str = Field(description="Explanation of how the deployments correlate with the logs")
    is_suspicious_change: bool = Field(description="True if a recent deployment is highly likely to be the cause of the failure")

class RunbookAgentFinding(BaseModel):
    matching_runbooks: List[str] = Field(description="Names of runbooks matched")
    proposed_remediations: List[str] = Field(description="List of proposed fixes or actions retrieved from runbooks")

class RCAFinding(BaseModel):
    root_cause_hypothesis: str = Field(description="Detailed hypothesis of the root cause of the incident")
    confidence_score: float = Field(description="Confidence score in the root cause hypothesis (0.0 to 1.0)")
    evidence: str = Field(description="Synthesis of evidence from logs, metrics, and deployments that supports the hypothesis")

class ResponseFinding(BaseModel):
    remediation_steps: List[str] = Field(description="Actionable, step-by-step remediation commands/instructions")
    executive_summary: str = Field(description="A high-level business-focused summary of the incident and recovery plan")

class RemediationProposal(BaseModel):
    recommended_action: str = Field(description="Proposed action: rollback_deployment, restart_service, scale_replicas, clear_cache, no_action")
    target_service: str = Field(description="Target service name (e.g., order-service)")
    target_version: Optional[str] = Field(None, description="Version to deploy (for rollback_deployment)")
    risk_level: str = Field(description="Risk level: low, medium, high")
    reasoning: str = Field(description="Reasoning for the proposal")
    requires_approval: bool = Field(default=True, description="True if action requires operator approval")

class TimelineEvent(BaseModel):
    timestamp: str
    event_type: str
    description: str

class IncidentTimeline(BaseModel):
    events: List[TimelineEvent]

class HistoricalContext(BaseModel):
    similar_incidents_found: int = Field(description="Number of similar incidents found in history")
    recommended_fix: str = Field(description="Historical recommended fix description")
    historical_success_rate: float = Field(description="Success rate of the recommended fix (0.0 to 1.0)")

class AnomalyFinding(BaseModel):
    anomaly_detected: bool
    anomaly_type: str
    confidence: float
    affected_service: str
    description: str

class ClassificationFinding(BaseModel):
    incident_type: str = Field(description="Incident type: database, cache, networking, deployment, infrastructure, application, security, unknown")
    severity: str = Field(description="Incident severity level")
    affected_domain: str = Field(description="Affected domain or component")
    confidence: float = Field(description="Confidence score in the classification (0.0 to 1.0)")


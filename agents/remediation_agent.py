import os
import logging
from datetime import datetime
from typing import Dict, Any
from agents.state import IncidentState
from agents.models import RemediationProposal
from langchain_google_genai import ChatGoogleGenerativeAI
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.remediation_agent")

async def remediation_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Auto Remediation Agent Node:
    Analyzes RCA hypothesis, confidence score, deployment findings, and runbook findings,
    and proposes a remediation action (e.g. rollback_deployment, restart_service, etc.).
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "remediation_agent", 
            "running",
            message="Evaluating risk parameters and formulating automated remediation plan..."
        )
        
    logger.info("Starting Remediation Agent...")
    
    rca = state.get("rca_findings")
    deploy = state.get("deployment_findings")
    runbook = state.get("runbook_findings")
    
    rca_str = rca.model_dump_json() if rca and hasattr(rca, "model_dump_json") else str(rca)
    deploy_str = deploy.model_dump_json() if deploy and hasattr(deploy, "model_dump_json") else str(deploy)
    runbook_str = runbook.model_dump_json() if runbook and hasattr(runbook, "model_dump_json") else str(runbook)
    
    from config.environment import get_active_profile
    active_profile = get_active_profile()
    services_list = active_profile.services
    
    prompt = f"""
    You are the Auto Remediation Agent of OpsPilot AI. Based on the incident findings below, propose a remediation action.
    
    Root Cause Analysis (RCA) Findings:
    {rca_str}
    
    Deployment Findings:
    {deploy_str}
    
    Runbook Findings:
    {runbook_str}
    
    Environment Context:
    - Environment Type: {active_profile.environment_type}
    - Services in scope: {services_list}
    
    Please evaluate the incident and select one of the following recommended actions:
    1. rollback_deployment
    2. restart_service
    3. scale_replicas
    4. clear_cache
    5. no_action
    
    Formulate a RemediationProposal with the following fields:
    - recommended_action: The selected action (must be exactly one of the five supported actions).
    - target_service: The name of the service affected (must be one of the environment's services: {services_list}, or 'unknown').
    - target_version: The version to deploy (specifically for rollback_deployment, e.g. v2.0.9).
    - risk_level: The risk level of the operation (low, medium, high).
    - reasoning: Rationale behind the chosen remediation action.
    - requires_approval: Whether this action requires operator approval (defaults to True).
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    
    remediation_llm = llm.with_structured_output(RemediationProposal)
    
    try:
        proposal = remediation_llm.invoke(prompt)
        logger.info(f"Remediation Proposal generated: {proposal}")
    except Exception as e:
        logger.error(f"Failed to generate remediation proposal: {e}")
        proposal = RemediationProposal(
            recommended_action="no_action",
            target_service="unknown",
            target_version=None,
            risk_level="low",
            reasoning=f"Failed to generate proposal due to error: {str(e)}",
            requires_approval=False
        )

    # Append event to timeline
    timeline = state.get("timeline") or []
    timeline.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": "remediation_proposal",
        "description": f"Remediation proposed: {proposal.recommended_action} on {proposal.target_service}"
    })

    if incident_id:
        await manager.send_status(
            incident_id, 
            "remediation_agent", 
            "completed",
            message=f"Remediation proposed: action='{proposal.recommended_action}', target_service='{proposal.target_service}', risk_level='{proposal.risk_level}'. Requires operator approval: {proposal.requires_approval}",
            data=proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
        )
        
    return {
        "remediation_proposal": proposal,
        "timeline": timeline
    }

import logging
import os
from datetime import datetime
from typing import Dict, Any
from agents.state import IncidentState
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.approval")

async def approval_node(state: IncidentState) -> Dict[str, Any]:
    """
    Approval Node:
    Executes and logs the remediation action if approved.
    Writes execution status to reports/actions.log.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "approval_node", 
            "running",
            message="Workflow paused. Awaiting operator approval of the remediation proposal..."
        )
        
    logger.info("Executing Approval Node...")
    
    approval_status = state.get("approval_status")
    proposal = state.get("remediation_proposal")
    
    if approval_status and approval_status.get("approved") and proposal:
        logger.info(f"Remediation action approved: {proposal}")
        
        # Determine service and action
        action = proposal.recommended_action
        if action == "rollback_deployment":
            action = "rollback"
            
        target_service = proposal.target_service
        target_version = proposal.target_version
        
        # Format the log line exactly as required
        version_str = f" {target_version}" if target_version else ""
        log_entry = f"[APPROVED]\n{action} {target_service}{version_str}\n"
        
        # Write to reports/actions.log
        os.makedirs("reports", exist_ok=True)
        actions_log_path = "reports/actions.log"
        with open(actions_log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
            
        logger.info(f"Remediation action successfully logged to {actions_log_path}")
    else:
        logger.info("No approval given or no proposal found. Remediation skipped.")

    # Log to timeline if proposal and approval decision are available
    timeline = state.get("timeline") or []
    if approval_status and proposal:
        approved = approval_status.get("approved")
        decision_str = "Approved" if approved else "Rejected"
        timeline.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": "approval",
            "description": f"Operator decision: {decision_str} for {proposal.recommended_action} on {proposal.target_service}"
        })

    if incident_id:
        approved = approval_status.get("approved") if approval_status else False
        await manager.send_status(
            incident_id, 
            "approval_node", 
            "completed",
            message=f"Operator decision processed: {'Remediation action APPROVED and executed' if approved else 'Remediation action REJECTED by operator'}."
        )
        
    return {
        "timeline": timeline
    }

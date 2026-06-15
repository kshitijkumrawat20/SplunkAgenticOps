import logging
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
from .state import IncidentState
from .nodes import (
    log_agent_node,
    metrics_agent_node,
    deployment_agent_node,
    runbook_agent_node,
    rca_agent_node,
    response_agent_node
)

logger = logging.getLogger("opspilot.graph")

def supervisor_node(state: IncidentState) -> Dict[str, Any]:
    """
    Supervisor Node: Orchestrates the sequential worker execution.
    It checks which findings are missing and routes to the next worker.
    Once all workers complete, it routes to the RCA agent.
    """
    logger.info("Supervisor orchestrating next step...")
    
    # Check what findings are missing
    if not state.get("log_findings"):
        logger.info("Supervisor routing to Log Agent.")
        return {"supervisor_next": "log_agent"}
        
    if not state.get("metrics_findings"):
        logger.info("Supervisor routing to Metrics Agent.")
        return {"supervisor_next": "metrics_agent"}
        
    if not state.get("deployment_findings"):
        logger.info("Supervisor routing to Deployment Agent.")
        return {"supervisor_next": "deployment_agent"}
        
    if not state.get("runbook_findings"):
        logger.info("Supervisor routing to Runbook Agent.")
        return {"supervisor_next": "runbook_agent"}
        
    logger.info("Supervisor routing to RCA Agent.")
    return {"supervisor_next": "rca_agent"}

def supervisor_router(state: IncidentState) -> Literal["log_agent", "metrics_agent", "deployment_agent", "runbook_agent", "rca_agent"]:
    """Routes based on the supervisor's decision."""
    next_node = state.get("supervisor_next")
    if next_node in ["log_agent", "metrics_agent", "deployment_agent", "runbook_agent", "rca_agent"]:
        return next_node
    return "rca_agent"

# Build StateGraph
workflow = StateGraph(IncidentState)

# Add nodes
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("log_agent", log_agent_node)
workflow.add_node("metrics_agent", metrics_agent_node)
workflow.add_node("deployment_agent", deployment_agent_node)
workflow.add_node("runbook_agent", runbook_agent_node)
workflow.add_node("rca_agent", rca_agent_node)
workflow.add_node("response_agent", response_agent_node)

# Set entry point
workflow.set_entry_point("supervisor")

# Configure conditional edges from supervisor
workflow.add_conditional_edges(
    "supervisor",
    supervisor_router,
    {
        "log_agent": "log_agent",
        "metrics_agent": "metrics_agent",
        "deployment_agent": "deployment_agent",
        "runbook_agent": "runbook_agent",
        "rca_agent": "rca_agent"
    }
)

# Connect workers back to supervisor for next decision
workflow.add_edge("log_agent", "supervisor")
workflow.add_edge("metrics_agent", "supervisor")
workflow.add_edge("deployment_agent", "supervisor")
workflow.add_edge("runbook_agent", "supervisor")

# Connect RCA to Response agent, then END
workflow.add_edge("rca_agent", "response_agent")
workflow.add_edge("response_agent", END)

# Compile graph
graph = workflow.compile()

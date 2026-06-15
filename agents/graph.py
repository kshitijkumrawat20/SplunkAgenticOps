import logging
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from .state import IncidentState

# Import post-investigation nodes
from .remediation_agent import remediation_agent_node
from .approval import approval_node
from .nodes import rca_agent_node, response_agent_node

# Import planner and registry
from .planner_agent import planner_agent_node
from .registry import AGENT_REGISTRY

logger = logging.getLogger("opspilot.graph")

def supervisor_node(state: IncidentState) -> Dict[str, Any]:
    """
    Supervisor Node: Orchestrates the sequential worker execution.
    It inspects the generated InvestigationPlan, finds the next unexecuted agent,
    and routes to it. Once all selected agents finish, it routes to the RCA agent.
    """
    logger.info("Supervisor orchestrating next step...")
    
    # 1. First, make sure the planner has run to create the plan
    plan = state.get("investigation_plan")
    if not plan:
        logger.info("Supervisor routing to Planner Agent.")
        return {"supervisor_next": "planner_agent"}
        
    if isinstance(plan, dict):
        required_agents = plan.get("required_agents") or []
    else:
        required_agents = getattr(plan, "required_agents", []) or []
    
    # 2. Check each required agent in the plan
    for agent_id in required_agents:
        has_findings = False
        
        # Check standard agent findings
        if agent_id == "log_agent":
            has_findings = state.get("log_findings") is not None
        elif agent_id == "metrics_agent":
            has_findings = state.get("metrics_findings") is not None
        elif agent_id == "anomaly_agent":
            has_findings = state.get("anomaly_findings") is not None
        elif agent_id == "deployment_agent":
            has_findings = state.get("deployment_findings") is not None
        elif agent_id == "runbook_agent":
            has_findings = state.get("runbook_findings") is not None
        elif agent_id == "timeline_agent":
            has_findings = state.get("timeline") is not None
        elif agent_id == "memory_agent":
            has_findings = state.get("historical_context") is not None
        else:
            # Check domain-specific registry agent findings
            domain_findings = state.get("domain_findings") or {}
            has_findings = agent_id in domain_findings
            
        if not has_findings:
            logger.info(f"Supervisor routing to next unexecuted agent: {agent_id}")
            return {"supervisor_next": agent_id}
            
    logger.info("All planned investigation agents completed. Supervisor routing to RCA Agent.")
    return {"supervisor_next": "rca_agent"}

def supervisor_router(state: IncidentState) -> str:
    """Routes based on the supervisor's decision."""
    next_node = state.get("supervisor_next")
    if next_node:
        return next_node
    return "rca_agent"

# Build StateGraph
workflow = StateGraph(IncidentState)

# Add standard workflow nodes
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("planner_agent", planner_agent_node)
workflow.add_node("rca_agent", rca_agent_node)
workflow.add_node("remediation_agent", remediation_agent_node)
workflow.add_node("approval_node", approval_node)
workflow.add_node("response_agent", response_agent_node)

# Set entry point
workflow.set_entry_point("supervisor")

# Connect planner back to supervisor
workflow.add_edge("planner_agent", "supervisor")

# Add all registry agents dynamically to the workflow
for agent_id, agent_node in AGENT_REGISTRY.items():
    logger.info(f"Dynamically registering registry agent '{agent_id}' to LangGraph workflow.")
    workflow.add_node(agent_id, agent_node)
    workflow.add_edge(agent_id, "supervisor")

# Build the conditional routing map dynamically
routing_map = {
    "planner_agent": "planner_agent",
    "rca_agent": "rca_agent"
}
for agent_id in AGENT_REGISTRY.keys():
    routing_map[agent_id] = agent_id

# Configure conditional edges from supervisor
workflow.add_conditional_edges(
    "supervisor",
    supervisor_router,
    routing_map
)

# Connect RCA to Remediation, then Approval (Paused/Breakpoint), then Response, then END
workflow.add_edge("rca_agent", "remediation_agent")
workflow.add_edge("remediation_agent", "approval_node")
workflow.add_edge("approval_node", "response_agent")
workflow.add_edge("response_agent", END)

# Compile graph
memory = MemorySaver()
graph = workflow.compile(checkpointer=memory, interrupt_before=["approval_node"])

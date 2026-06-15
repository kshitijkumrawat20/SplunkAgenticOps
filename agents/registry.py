import logging
from typing import Dict, Any, Callable

# Import existing nodes
from agents.nodes import (
    log_agent_node,
    metrics_agent_node,
    deployment_agent_node,
    runbook_agent_node
)
from agents.timeline_agent import timeline_agent_node
from agents.memory_agent import memory_agent_node
from agents.anomaly_agent import anomaly_agent_node

# Import domain nodes
from agents.domain.database_agent import database_agent_node
from agents.domain.network_agent import network_agent_node
from agents.domain.security_agent import security_agent_node
from agents.domain.kubernetes_agent import kubernetes_agent_node
from agents.domain.application_agent import application_agent_node
from agents.domain.infrastructure_agent import infrastructure_agent_node

logger = logging.getLogger("opspilot.registry")

AGENT_REGISTRY: Dict[str, Callable] = {
    "log_agent": log_agent_node,
    "metrics_agent": metrics_agent_node,
    "anomaly_agent": anomaly_agent_node,
    "deployment_agent": deployment_agent_node,
    "runbook_agent": runbook_agent_node,
    "timeline_agent": timeline_agent_node,
    "memory_agent": memory_agent_node,
    "database_agent": database_agent_node,
    "network_agent": network_agent_node,
    "security_agent": security_agent_node,
    "kubernetes_agent": kubernetes_agent_node,
    "application_agent": application_agent_node,
    "infrastructure_agent": infrastructure_agent_node
}

def get_agent_node(agent_id: str) -> Callable:
    if agent_id not in AGENT_REGISTRY:
        raise ValueError(f"Agent '{agent_id}' is not registered.")
    return AGENT_REGISTRY[agent_id]

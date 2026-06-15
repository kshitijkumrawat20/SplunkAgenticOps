import os
import logging
import json
import re
from datetime import datetime
from typing import Dict, Any, List
from agents.state import IncidentState
from agents.models import AnomalyFinding
from langchain_google_genai import ChatGoogleGenerativeAI
from api.websocket_manager import manager

logger = logging.getLogger("opspilot.anomaly_agent")

def calculate_z_score_deviation(log_lines: List[str]) -> Dict[str, Any]:
    """
    Computes statistical metrics (mean, std dev, z-score of the latest error rate)
    by parsing timestamps from raw logs.
    """
    # Regex to match timestamps like "2026-06-14 23:37:10" or ISO formats
    time_regex = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")
    timestamps = []
    
    for line in log_lines:
        match = time_regex.search(line)
        if match:
            try:
                # Parse to datetime
                ts_str = match.group(1).replace("T", " ")
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                timestamps.append(ts.timestamp())
            except Exception:
                continue

    if len(timestamps) < 5:
        # Insufficient data for statistical analysis
        return {
            "z_score": 0.0,
            "spike_detected": False,
            "rolling_average": len(log_lines),
            "deviation_percentage": 0.0
        }
        
    timestamps.sort()
    start_time = timestamps[0]
    end_time = timestamps[-1]
    duration = end_time - start_time
    
    if duration <= 0:
        return {
            "z_score": 3.0, # All errors occurred at the same second -> absolute spike
            "spike_detected": True,
            "rolling_average": len(log_lines),
            "deviation_percentage": 100.0
        }
        
    # Split duration into 10 intervals and count frequency in each
    interval_len = duration / 10
    buckets = [0] * 10
    
    for ts in timestamps:
        idx = int((ts - start_time) / interval_len)
        if idx >= 10:
            idx = 9
        buckets[idx] += 1
        
    # Calculate rolling average (mean of first 9 buckets as baseline)
    baseline_buckets = buckets[:9]
    mean = sum(baseline_buckets) / len(baseline_buckets)
    
    # Calculate standard deviation
    variance = sum((x - mean) ** 2 for x in baseline_buckets) / len(baseline_buckets)
    std_dev = variance ** 0.5
    
    # Latest interval count
    latest_count = buckets[9]
    
    # Compute Z-score
    if std_dev > 0:
        z_score = (latest_count - mean) / std_dev
    else:
        z_score = 3.0 if latest_count > mean else 0.0
        
    deviation_pct = 0.0
    if mean > 0:
        deviation_pct = ((latest_count - mean) / mean) * 100.0
        
    return {
        "z_score": round(z_score, 2),
        "spike_detected": z_score >= 2.0 or deviation_pct >= 200.0,
        "rolling_average": round(mean, 2),
        "deviation_percentage": round(deviation_pct, 2),
        "latest_interval_count": latest_count,
        "total_errors": len(log_lines)
    }

async def anomaly_agent_node(state: IncidentState) -> Dict[str, Any]:
    """
    Anomaly Detection Agent Node:
    Performs statistical spike checks on incident error volumes and generates findings.
    """
    incident_id = state.get("incident_id")
    if incident_id:
        await manager.send_status(
            incident_id, 
            "anomaly_agent", 
            "running",
            message="Running statistical baseline rolling averages and Z-score deviation check..."
        )
        
    logger.info("Starting Anomaly Detection Agent...")
    
    raw_logs = state.get("raw_logs", [])
    log = state.get("log_findings")
    metrics = state.get("metrics_findings")
    
    # Calculate statistical metrics
    stats = calculate_z_score_deviation(raw_logs)
    
    log_str = log.model_dump_json() if log and hasattr(log, "model_dump_json") else str(log)
    metrics_str = metrics.model_dump_json() if metrics and hasattr(metrics, "model_dump_json") else str(metrics)
    
    prompt = f"""
    You are the Anomaly Detection Agent of OpsPilot AI. Analyze the statistical data and error context below to detect abnormal operational behavior.
    
    Error Context findings:
    {log_str}
    
    Error Volume Metrics:
    {metrics_str}
    
    Statistical Calculations:
    - Z-Score Deviation: {stats['z_score']}
    - Volume Spike Detected: {stats['spike_detected']}
    - Baseline Rolling Average (per interval): {stats['rolling_average']}
    - Latest Deviation Percentage: {stats['deviation_percentage']}%
    - Latest count vs baseline: {stats.get('latest_interval_count', 0)} vs {stats['rolling_average']}
    - Total error records: {stats['total_errors']}
    
    Please formulate an AnomalyFinding JSON containing:
    - anomaly_detected: True if there is a statistical spike (e.g. Z-score >= 2 or high deviation), otherwise False.
    - anomaly_type: One of 'error_spike', 'latency_increase', 'deployment_correlation', 'none'.
    - confidence: A confidence level between 0.0 and 1.0 (based on statistical z-score or volume deviation).
    - affected_service: The service impacted by the anomaly (e.g. order-service).
    - description: A clear description summarizing the anomaly (e.g. 'Database timeout errors increased 450% above baseline').
    """
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    
    anomaly_llm = llm.with_structured_output(AnomalyFinding)
    
    try:
        findings = anomaly_llm.invoke(prompt)
        # Ensure that if stats indicated spike, we capture it
        if stats['spike_detected'] and not findings.anomaly_detected:
            findings.anomaly_detected = True
            findings.anomaly_type = "error_spike"
            findings.confidence = max(findings.confidence, 0.90)
            
        logger.info(f"Anomaly findings: {findings}")
    except Exception as e:
        logger.error(f"Failed to run anomaly detection: {e}")
        # Fallback anomaly finding
        fallback_service = "unknown"
        if log and hasattr(log, "affected_services") and log.affected_services:
            fallback_service = log.affected_services[0]
        else:
            from config.environment import get_active_profile
            prof = get_active_profile()
            if prof.services:
                fallback_service = prof.services[0]

        findings = AnomalyFinding(
            anomaly_detected=stats['spike_detected'],
            anomaly_type="error_spike" if stats['spike_detected'] else "none",
            confidence=0.80 if stats['spike_detected'] else 1.0,
            affected_service=fallback_service,
            description=f"Statistical spike of {stats['deviation_percentage']}% detected."
        )
        
    if incident_id:
        await manager.send_status(
            incident_id, 
            "anomaly_agent", 
            "completed",
            message=f"Anomaly check complete. Detected: {findings.anomaly_detected} ({findings.anomaly_type}). description: {findings.description}",
            data=findings.model_dump() if hasattr(findings, "model_dump") else findings
        )
        
    return {
        "anomaly_findings": findings
    }

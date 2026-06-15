import asyncio
import os
import json
import logging
from dotenv import load_dotenv

# Configure logging to console
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("opspilot.verify")

load_dotenv()

async def verify_all():
    # Import main API app and graph
    from api.main import health_check, run_investigation, InvestigationRequest
    from agents import graph
    
    logger.info("========================================")
    logger.info("Starting OpsPilot AI End-to-End Verification")
    logger.info("========================================")
    
    # Test 1: Health Check (Splunk MCP Connectivity)
    logger.info("\n--- TEST 1: Running API Health Check ---")
    try:
        health_res = await health_check()
        logger.info(f"Health Check Response: {json.dumps(health_res, indent=2)}")
        if health_res.get("splunk_mcp_connected"):
            logger.info("SUCCESS: Splunk MCP Server is connected and query works!")
        else:
            logger.info(f"WARNING: Splunk MCP Server connection failed: {health_res.get('splunk_mcp_error')}")
    except Exception as e:
        logger.error(f"Health Check failed: {e}")

    # Test 2: LangGraph Incident Investigation
    logger.info("\n--- TEST 2: Running Incident Investigation Workflow ---")
    req = InvestigationRequest(
        alert_name="E-Commerce Database Outage",
        index="opspilot_logs",
        error_query="search index=opspilot_logs ERROR earliest=-24h",
        earliest_time="-24h",
        latest_time="now"
    )
    
    try:
        logger.info("Executing LangGraph investigation workflow...")
        investigation_res = await run_investigation(req)
        logger.info("SUCCESS: Investigation workflow completed successfully!")
        
        # Display sample output of findings
        findings = investigation_res.get("findings", {})
        rca = findings.get("rca_findings")
        resp = findings.get("response_findings")
        
        if rca:
            logger.info(f"\nRoot Cause Hypothesis (Confidence: {rca.confidence_score}):")
            logger.info(f"  {rca.root_cause_hypothesis}")
        if resp:
            logger.info("\nProposed Remediation Steps:")
            for idx, step in enumerate(resp.remediation_steps, 1):
                logger.info(f"  {idx}. {step}")
            logger.info(f"\nExecutive Summary:\n  {resp.executive_summary}")

        # Check if incident_report.json was generated
        report_path = "reports/incident_report.json"
        if os.path.exists(report_path):
            logger.info(f"\nSUCCESS: Incident report saved to {report_path}")
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = json.load(f)
                logger.info(f"Report timestamp: {report_content.get('timestamp')}")
                logger.info(f"Incident Name: {report_content.get('incident_name')}")
        else:
            logger.error("\nFAILURE: reports/incident_report.json was not found!")
            
    except Exception as e:
        logger.error(f"Incident investigation workflow failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_all())

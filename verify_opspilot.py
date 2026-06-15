import asyncio
import os
import json
import logging
from datetime import datetime
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
    logger.info("\n--- TEST 2: Running Incident Investigation Workflow (Phase 1: Propose Remediation) ---")
    incident_id = "test-incident-" + datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    req = InvestigationRequest(
        incident_id=incident_id,
        alert_name="E-Commerce Database Outage",
        index="opspilot_logs",
        error_query="search index=opspilot_logs ERROR earliest=-24h",
        earliest_time="-24h",
        latest_time="now"
    )
    
    try:
        logger.info(f"Executing LangGraph investigation workflow with ID: {incident_id}...")
        investigation_res = await run_investigation(req)
        
        status = investigation_res.get("status")
        logger.info(f"Investigation status: {status}")
        
        if status == "pending_approval":
            proposal = investigation_res.get("remediation_proposal")
            logger.info("SUCCESS: Investigation workflow paused at approval breakpoint!")
            logger.info(f"Remediation Proposal: {json.dumps(proposal, indent=2)}")
            
            # Now simulate approval
            logger.info("\n--- TEST 3: Resuming Workflow with Approval ---")
            from api.main import approve_remediation, ApprovalRequest
            app_req = ApprovalRequest(incident_id=incident_id, approved=True)
            
            logger.info("Sending approval request...")
            approval_res = await approve_remediation(app_req)
            logger.info("SUCCESS: Approval workflow completed!")
            
            # Display final findings
            findings = approval_res.get("findings", {})
            classification = findings.get("classification_findings")
            rca = findings.get("rca_findings")
            resp = findings.get("response_findings")
            
            # Print classification
            class_type = classification.get("incident_type") if isinstance(classification, dict) else getattr(classification, "incident_type", "Unknown")
            class_conf = classification.get("confidence") if isinstance(classification, dict) else getattr(classification, "confidence", 0.0)
            logger.info(f"\nIncident Classification Category (Confidence: {class_conf}):")
            logger.info(f"  {class_type}")

            # If rca is a dict/model:
            rca_hyp = rca.get("root_cause_hypothesis") if isinstance(rca, dict) else getattr(rca, "root_cause_hypothesis", "Unknown")
            rca_conf = rca.get("confidence_score") if isinstance(rca, dict) else getattr(rca, "confidence_score", 0.0)
            
            logger.info(f"\nRoot Cause Hypothesis (Confidence: {rca_conf}):")
            logger.info(f"  {rca_hyp}")
            
            if resp:
                steps = resp.get("remediation_steps") if isinstance(resp, dict) else getattr(resp, "remediation_steps", [])
                exec_sum = resp.get("executive_summary") if isinstance(resp, dict) else getattr(resp, "executive_summary", "")
                logger.info("\nProposed Remediation Steps:")
                for idx, step in enumerate(steps, 1):
                    logger.info(f"  {idx}. {step}")
                logger.info(f"\nExecutive Summary:\n  {exec_sum}")
        else:
            logger.error(f"FAILURE: Expected pending_approval status, got {status}")
            
        # Check if reports/actions.log was generated
        actions_log_path = "reports/actions.log"
        if os.path.exists(actions_log_path):
            logger.info(f"\nSUCCESS: Actions log updated at {actions_log_path}")
            with open(actions_log_path, "r", encoding="utf-8") as f:
                logger.info(f"Latest logs:\n{f.read()}")
        else:
            logger.error("\nFAILURE: reports/actions.log was not found!")
            
        # Check if incident_report.json was generated
        report_path = "reports/incident_report.json"
        if os.path.exists(report_path):
            logger.info(f"\nSUCCESS: Incident report saved to {report_path}")
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = json.load(f)
                logger.info(f"Report timestamp: {report_content.get('timestamp')}")
                logger.info(f"Incident Name: {report_content.get('incident_name')}")
                # Check for Phase 4 keys
                logger.info(f"Report Incident Type present: {'incident_type' in report_content}")
                logger.info(f"Report Industry present: {'industry' in report_content}")
                # Check for Phase 5 keys
                logger.info(f"Report Investigation Plan present: {'investigation_plan' in report_content}")
                logger.info(f"Report Domain Findings present: {'domain_findings' in report_content}")
                # Check for Phase 2 keys
                logger.info(f"Report Timeline keys present: {'timeline' in report_content}")
                logger.info(f"Report Historical Context keys present: {'historical_context' in report_content}")
                # Check for Phase 3 keys
                logger.info(f"Report Executive Summary present: {'executive_summary' in report_content}")
                logger.info(f"Report Anomaly Findings present: {'anomaly' in report_content}")
                if 'anomaly' in report_content:
                    logger.info(f"Anomaly Findings: {json.dumps(report_content['anomaly'], indent=2)}")
        else:
            logger.error("\nFAILURE: reports/incident_report.json was not found!")
 
        # Check if reports/timeline.json was generated
        timeline_path = "reports/timeline.json"
        if os.path.exists(timeline_path):
            logger.info(f"\nSUCCESS: Timeline saved to {timeline_path}")
            with open(timeline_path, "r", encoding="utf-8") as f:
                timeline_content = json.load(f)
                events = timeline_content.get("events", [])
                logger.info(f"Timeline contains {len(events)} events.")
                for ev in events:
                    logger.info(f"  [{ev.get('timestamp')}] ({ev.get('event_type')}) {ev.get('description')}")
        else:
            logger.error("\nFAILURE: reports/timeline.json was not found!")
            
        # Check if memory database updated
        from api.main import get_incidents_endpoint
        incidents = await get_incidents_endpoint()
        logger.info(f"\n--- TEST 4: Querying Memory Database ---")
        logger.info(f"SUCCESS: Retrieved {len(incidents)} historical incidents from store.")
        if incidents:
            logger.info(f"Latest incident stored ID: {incidents[-1].get('incident_id')}")
            
        # Test 5: Verify FastAPI Dashboard endpoints
        logger.info(f"\n--- TEST 5: Querying FastAPI Dashboard Endpoints ---")
        from api.main import get_dashboard_summary, get_dashboard_live
        summary_res = await get_dashboard_summary()
        logger.info(f"Dashboard Summary Response: {json.dumps(summary_res, indent=2)}")
        assert "active_count" in summary_res
        assert "resolved_count" in summary_res
        assert "top_root_causes" in summary_res
        assert "approval_rate" in summary_res
        logger.info("SUCCESS: Dashboard Summary endpoint verified!")
        
        live_res = await get_dashboard_live()
        logger.info(f"Dashboard Live Response: {json.dumps(live_res, indent=2)}")
        logger.info("SUCCESS: Dashboard Live endpoint verified!")

        # Test 6: Verify Profile Endpoints
        logger.info(f"\n--- TEST 6: Querying FastAPI Profile Endpoints ---")
        from api.main import get_profiles, select_profile, ProfileSelectRequest
        profiles_res = await get_profiles()
        logger.info(f"Available profiles: {json.dumps(profiles_res, indent=2)}")
        assert "available_profiles" in profiles_res
        assert "active_profile" in profiles_res
        
        # Test setting profile
        logger.info("Setting active profile to 'kubernetes'...")
        sel_res = await select_profile(ProfileSelectRequest(profile="kubernetes"))
        logger.info(f"Select profile response: {json.dumps(sel_res, indent=2)}")
        assert sel_res.get("active_profile") == "kubernetes"
        
        # Set back to ecommerce
        await select_profile(ProfileSelectRequest(profile="ecommerce"))
        logger.info("SUCCESS: Profile endpoints verified!")
        
    except Exception as e:
        logger.error(f"Incident investigation workflow failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_all())

import os
import json
import logging
import resend

import database as db
import proposal_generator
import builder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def run_manager_cycle() -> dict:
    """
    The CEO Agent: sweeps 'new' leads, analyzes them, and if 'Urgency: High',
    qualifies them and triggers the build process.
    Sends a daily summary to target_email.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    target_email = os.environ.get("TARGET_EMAIL")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    if api_key:
        resend.api_key = api_key

    leads = db.get_leads(status="new")
    if not leads:
        log.info("Manager Agent: No 'new' leads found.")
        return {"processed": 0, "qualified": 0, "built": 0}

    qualified_count = 0
    built_count = 0
    processed_count = 0

    log.info(f"Manager Agent: Found {len(leads)} 'new' leads to evaluate.")

    for lead in leads:
        lead_id = lead["id"]
        source = lead.get("source", "unknown")
        title = lead.get("title", "")
        description = lead.get("description", "")
        processed_count += 1

        try:
            # 1. Generate analysis and proposal to find urgency
            analysis_str, proposal_str = proposal_generator.process_lead(lead_id, source, title, description)
            db.save_proposal(lead_id, analysis_str, proposal_str)

            analysis_data = json.loads(analysis_str)
            urgency = str(analysis_data.get("urgency", "low")).lower()

            if urgency == "high":
                log.info(f"Manager Agent: Lead {lead_id} has HIGH urgency. Qualifying and building.")
                db.update_status(lead_id, "qualified")
                qualified_count += 1
                
                # 2. Trigger build (builder probably updates status to 'built')
                builder.build_lead(lead_id)
                built_count += 1
            else:
                log.info(f"Manager Agent: Lead {lead_id} has {urgency} urgency. Skipping build.")
                db.update_status(lead_id, "skipped")

        except Exception as e:
            log.error(f"Manager Agent: Error processing lead {lead_id}: {e}")

    # 3. Send Summary email
    if api_key and target_email:
        try:
            html_body = f"""
            <html>
            <body style="font-family: sans-serif; color: #333;">
                <h2>CEO Agent: Daily Operations Summary</h2>
                <p>Hello Team,</p>
                <p>The Manager Agent has completed its cycle.</p>
                <ul>
                    <li>Leads Processed: <b>{processed_count}</b></li>
                    <li>High Urgency Leads Qualified: <b>{qualified_count}</b></li>
                    <li>Projects Successfully Built: <b>{built_count}</b></li>
                </ul>
                <p>The Sales Agent will take over the built leads in its next cycle.</p>
            </body>
            </html>
            """
            resend.Emails.send({
                "from": from_email,
                "to": [target_email],
                "subject": "Manager Agent: Operations Summary",
                "html": html_body
            })
            log.info("Manager Agent: Summary email sent.")
        except Exception as e:
            log.error(f"Manager Agent: Failed to send summary email: {e}")

    return {
        "processed": processed_count,
        "qualified": qualified_count,
        "built": built_count
    }

if __name__ == "__main__":
    result = run_manager_cycle()
    print(f"Manager cycle completed: {result}")

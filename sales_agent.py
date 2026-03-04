import os
import json
import logging
import base64
import resend
import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def run_sales_cycle() -> int:
    """
    Finds all 'built' leads, sends an email with the proposal and ZIP deliverable, 
    then marks them as 'sent' in the database.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        log.error("RESEND_API_KEY is not set. Cannot run sales cycle.")
        return 0
    resend.api_key = api_key

    target_email = os.environ.get("TARGET_EMAIL")
    if not target_email:
        log.error("TARGET_EMAIL is not set. Don't know where to send the emails.")
        return 0

    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    leads = db.get_leads(status="built")
    if not leads:
        log.info("No leads with 'built' status found.")
        return 0

    sent_count = 0
    for lead in leads:
        lead_id = lead["id"]
        title = lead.get("title", "Unknown Project")
        proposal_raw = lead.get("proposal", "{}")
        analysis_raw = lead.get("analysis", "{}")
        deliverable_path = lead.get("deliverable_path")

        if not deliverable_path or not os.path.exists(deliverable_path):
            log.warning(f"Lead {lead_id} missing deliverable: {deliverable_path}")
            continue

        try:
            analysis_dict = json.loads(analysis_raw)
            problem_summary = analysis_dict.get("problem_summary", "We identified your key business challenges.")
        except Exception:
            problem_summary = "We identified your key business challenges based on your request."

        try:
            proposal_dict = json.loads(proposal_raw)
            technical_solution = proposal_dict.get("proposal", str(proposal_dict))
            if not isinstance(technical_solution, str):
                technical_solution = json.dumps(technical_solution, indent=2)
        except Exception:
            technical_solution = proposal_raw

        try:
            with open(deliverable_path, "rb") as f:
                file_bytes = f.read()
                # Use list of bytes for Resend Python SDK
                file_content = list(file_bytes)
        except Exception as e:
            log.error(f"Failed to read deliverable {deliverable_path}: {e}")
            continue

        html_body = f"""
        <html>
        <body>
            <h2>Your Custom Project: {title}</h2>
            <p>Hi there,</p>
            <p>Based on your project description, we've developed a custom technical solution for you.</p>
            
            <h3>Problem Summary</h3>
            <p>{problem_summary}</p>
            
            <h3>Technical Solution</h3>
            <pre style="background: #f4f4f4; padding: 15px; border-radius: 5px; font-family: monospace;">{technical_solution}</pre>
            
            <p>We've attached the fully functional code project as a ZIP file to this email.</p>
            
            <h3>Let's Schedule a Demo</h3>
            <p>We'd love to invite you to a brief 15-minute demonstration call to walk you through the solution we built.</p>
            <p>Please reply to this email, and we'll schedule a time that works for you.</p>
            
            <p>Best regards,<br/>The Engineering Team</p>
        </body>
        </html>
        """

        try:
            params = {
                "from": from_email,
                "to": [target_email],
                "subject": f"Your automated solution is ready: {title}",
                "html": html_body,
                "attachments": [
                    {
                        "filename": os.path.basename(deliverable_path),
                        "content": file_content
                    }
                ]
            }
            
            response = resend.Emails.send(params)
            log.info(f"Email sent successfully for lead {lead_id}: {response}")
            
            db.update_status(lead_id, "sent")
            sent_count += 1

        except Exception as e:
            log.error(f"Failed to send email for lead {lead_id}. Error: {e}")

    return sent_count

if __name__ == "__main__":
    count = run_sales_cycle()
    print(f"Sales cycle completed: sent {count} emails.")

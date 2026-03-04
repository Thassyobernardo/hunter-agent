import os
import json
import logging
import base64
import resend
import zipfile
import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def run_sales_cycle() -> int:
    """
    Finds all 'built' leads, sends an email with the proposal and ZIP deliverable, 
    then marks them as 'sent' in the database.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    resend.api_key = api_key

    target_email = os.environ.get("TARGET_EMAIL")
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

        analysis_dict = json.loads(analysis_raw)
        problem_summary = analysis_dict.get("problem_summary", "We identified your key business challenges.")

        proposal_dict = json.loads(proposal_raw)
        technical_solution = proposal_dict.get("proposal", str(proposal_dict))
        if not isinstance(technical_solution, str):
            technical_solution = json.dumps(technical_solution, indent=2)

        payment_link = os.environ.get("PAYMENT_LINK", "https://your-payment-link.com/")

        with zipfile.ZipFile(deliverable_path, 'r') as zf:
            file_list = zf.namelist()
            # Exclude root directory entries if they end with '/' to keep list clean
            clean_list = [f for f in file_list if not f.endswith('/')]
            # Render a tree-like/list output
            features_sample = "\n".join(f"- {f}" for f in clean_list[:20])
            if len(clean_list) > 20:
                features_sample += f"\n... and {len(clean_list) - 20} more items."

        html_body = f"""
        <html>
        <body style="font-family: sans-serif; color: #333; line-height: 1.6;">
            <h2>Your Custom Project: {title}</h2>
            <p>Hi there,</p>
            <p>Based on your project description, we've developed a custom technical solution for you.</p>
            
            <h3>Problem Summary</h3>
            <p>{problem_summary}</p>
            
            <h3>Technical Solution</h3>
            <pre style="background: #f4f4f4; padding: 15px; border-radius: 5px; font-family: monospace;">{technical_solution}</pre>
            
            <h3>Project Sample / Expected Deliverables</h3>
            <p>The original project has been successfully built and is securely stored on our servers. Here is a sample of the generated source code structure:</p>
            <pre style="background: #f4f4f4; padding: 15px; border-radius: 5px; font-family: monospace;">{features_sample}</pre>
            
            <h3>Unlock the Full Code</h3>
            <p>To automatically receive the full project ZIP file, please complete the payment using the link below:</p>
            <p><a href="{payment_link}" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Secure Your Code Now</a></p>
            
            <h3>Let's Schedule a Demo</h3>
            <p>If you'd like to see it in action before purchasing, we'd love to invite you to a brief 15-minute demonstration call.</p>
            <p>Please reply to this email, and we'll schedule a time that works for you.</p>
            
            <p>Best regards,<br/>The Engineering Team</p>
        </body>
        </html>
        """

        params = {
            "from": from_email,
            "to": [target_email],
            "subject": f"Your automated solution is ready: {title}",
            "html": html_body,
        }
        
        response = resend.Emails.send(params)
        log.info(f"Email sent successfully for lead {lead_id}: {response}")
        
        db.update_status(lead_id, "sent")
        sent_count += 1

    return sent_count

if __name__ == "__main__":
    count = run_sales_cycle()
    print(f"Sales cycle completed: sent {count} emails.")

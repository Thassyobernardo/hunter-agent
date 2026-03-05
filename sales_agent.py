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

    print(f"DEBUG: API Key (first 5): {str(api_key)[:5]}...")
    print(f"DEBUG: FROM Email (first 5): {str(from_email)[:5]}...")

    # Rate limiting: max 10 emails per day
    sent_today = db.count_recently_sent_leads(hours=24)
    if sent_today >= 10:
        log.info("[INFO] Daily limit of 10 leads reached. Resting until tomorrow.")
        return 0

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

        payment_link = os.environ.get("PAYMENT_LINK_URL", os.environ.get("PAYMENT_LINK", "https://your-payment-link.com/"))

        with zipfile.ZipFile(deliverable_path, 'r') as zf:
            file_list = zf.namelist()
            clean_list = [f for f in file_list if not f.endswith('/')]
            features_sample = "\n".join(f"- {f}" for f in clean_list[:20])
            if len(clean_list) > 20:
                features_sample += f"\n... and {len(clean_list) - 20} more items."

        html_body = f"""
        <html>
        <body style="font-family: sans-serif; color: #333; line-height: 1.6;">
            <h2>Seu Sistema Sob Medida: {title}</h2>
            <p>Olá!</p>
            <p>Preparamos uma ferramenta pronta para uso. Basta baixar o anexo, extrair a pasta e clicar duas vezes no arquivo <b>START_HERE.bat</b> para começar.</p>
            
            <p><a href="{payment_link}" style="display: inline-block; margin-top: 15px; padding: 15px 25px; background-color: #28a745; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">Liberar Acesso e Baixar Código Agora</a></p>
            
            <p>Se quiser ver tudo funcionando antes de decidir, basta responder a este e-mail e agendaremos uma rápida chamada de 15 minutos pelo Zoom.</p>
            
            <p>Um abraço,<br/>Equipe de Engenharia</p>
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

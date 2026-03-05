import os
import logging
import json
import time
import resend
import zipfile
import database as db

log = logging.getLogger(__name__)

# Templates for different sequence stages
STAGES = {
    0: {
        "subject": "Ready: Automation Prototype for {title}",
        "template": """
        <html>
        <body style="font-family: sans-serif; padding: 20px;">
            <h2>Seu Protótipo Personalizado</h2>
            <p>Olá! Desenvolvemos uma automação sob medida para: <b>{title}</b>.</p>
            <p>{hook}</p>
            <p>{agitation}</p>
            <p><b>Solução:</b> {solution}</p>
            <p>O código e instruções estão anexados. Para suporte e versão final:</p>
            <a href="{payment_url}" style="padding: 10px; background: #007bff; color: #fff; text-decoration: none;">Liberar Acesso</a>
            <p>{cta}</p>
        </body>
        </html>
        """
    },
    1: {
        "subject": "Follow-up: {title} Automation",
        "template": """
        <html>
        <body style="font-family: sans-serif; padding: 20px;">
            <h2>Alguma dúvida sobre o protótipo?</h2>
            <p>Olá! Notei que você ainda não acessou a versão final da automação para <b>{title}</b>.</p>
            <p>O motor que construímos resolve exatamente o gap de {pain}.</p>
            <p>Gostaria de agendar uma call técnica de 5 minutos?</p>
            <a href="{payment_url}">Link para Acesso Vitalício</a>
        </body>
        </html>
        """
    }
}

def run_sales_cycle() -> int:
    api_key = os.environ.get("RESEND_API_KEY")
    resend.api_key = api_key
    target_email = os.environ.get("TARGET_EMAIL")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    payment_link = os.environ.get("PAYMENT_LINK_URL", "https://buy.stripe.com/example")

    sent_count = 0

    # 1. New Leads (Stage 0)
    new_leads = db.get_leads(status="built")
    for lead in new_leads:
        try:
            proposal = json.loads(lead.get("proposal") or "{}")
            body = STAGES[0]["template"].format(
                title=lead["title"],
                hook=proposal.get("hook", ""),
                agitation=proposal.get("pas_agitation", ""),
                solution=proposal.get("pas_solution", ""),
                payment_url=payment_link,
                cta=proposal.get("call_to_action", "")
            )
            
            attachments = []
            if lead.get("deliverable_path") and os.path.exists(lead["deliverable_path"]):
                attachments.append({"filename": os.path.basename(lead["deliverable_path"]), "path": lead["deliverable_path"]})

            resend.Emails.send({
                "from": from_email,
                "to": [target_email],
                "subject": STAGES[0]["subject"].format(title=lead["title"][:50]),
                "html": body,
                "attachments": attachments
            })
            db.update_status(lead["id"], "sent")
            db.update_sequence_stage(lead["id"], 1)
            sent_count += 1
            log.info(f"Sales: Sent Stage 0 for lead {lead['id']}")
        except Exception as e:
            log.error(f"Sales Stage 0 Error: {e}")

    # 2. Follow-ups (Stage 1 -> 2)
    followups = db.get_followup_leads(days_since=1) # Reduced to 1 day for testing
    for lead in followups:
        try:
            analysis = json.loads(lead.get("analysis") or "{}")
            body = STAGES[1]["template"].format(
                title=lead["title"],
                pain=analysis.get("pain_points", ["trabalho manual"])[0],
                payment_url=payment_link
            )
            resend.Emails.send({
                "from": from_email,
                "to": [target_email],
                "subject": STAGES[1]["subject"].format(title=lead["title"][:50]),
                "html": body
            })
            db.update_sequence_stage(lead["id"], 2)
            sent_count += 1
            log.info(f"Sales: Sent Stage 1 follow-up for lead {lead['id']}")
        except Exception as e:
            log.error(f"Sales Stage 1 Error: {e}")

    return sent_count

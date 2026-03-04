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

    # Rate limiting: max 5 emails per day
    sent_today = db.count_recently_sent_leads(hours=24)
    if sent_today >= 5:
        log.info(f"Daily limit reached: {sent_today}/5 emails sent in the last 24h. Stopping sales cycle.")
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
            <p>Analisamos seu pedido e nossa engenharia já finalizou a criação do seu <b>Motor de Automação</b> exclusivo para o seu projeto.</p>
            
            <h3>O que é o Motor de Automação?</h3>
            <p>Trata-se de um sistema completo com código-fonte gerado especificamente para as suas necessidades de negócio, pronto para rodar no seu computador ou servidor.</p>
            
            <h3>Amostra da Estrutura Criada</h3>
            <p>O seu projeto já está armazenado de forma segura em nossos servidores. Aqui está uma prévia da arquitetura interna desenvolvida para você:</p>
            <pre style="background: #f4f4f4; padding: 15px; border-radius: 5px; font-family: monospace;">{features_sample}</pre>
            
            <h3>Como ativar seu sistema em 3 passos simples:</h3>
            <p>Para simplificar sua vida, nós configuramos um método onde você não precisa ser programador para iniciar tudo.</p>
            <ol>
                <li><b>Acesse o Link:</b> Clique no botão de liberação do código abaixo.</li>
                <li><b>Baixe o Projeto:</b> Você receberá o download do arquivo ZIP contendo todo o seu sistema.</li>
                <li><b>Inicie a Mágica:</b> Extraia a pasta, dê <b>dois cliques</b> no arquivo <code>INICIAR.bat</code> e o sistema fará toda a instalação sozinho!</li>
            </ol>
            
            <p><a href="{payment_link}" style="display: inline-block; margin-top: 15px; padding: 15px 25px; background-color: #28a745; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">Liberar Acesso e Baixar Código Agora</a></p>
            
            <h3>Precisa de uma demonstração?</h3>
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

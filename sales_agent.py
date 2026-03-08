import os
import logging
import time
import resend
import database as db

log = logging.getLogger(__name__)

# Templates
TEMPLATES = {
    "french": {
        "dental": {
            "subject": "Automatisation IA pour {name} — +40% de patients sans effort",
            "body": """
Bonjour,

J'ai découvert {name} et je me permets de vous contacter avec une proposition concrète.

Chez Claw Agency, nous aidons les cliniques dentaires au Luxembourg à automatiser leur prospection et leur communication — sans changer leurs outils existants.

Ce que nous mettons en place pour vous :
- Réponses automatiques aux demandes de rendez-vous 24h/24
- Suivi automatique des patients par email/SMS
- Rapport hebdomadaire de performance
- Chatbot multilingue pour votre site web

L'impact moyen pour nos clients :
→ +40% de demandes de rendez-vous traitées
→ -3h de travail administratif par jour
→ Réponse aux patients en moins de 2 minutes

Vous pouvez voir nos services ici : https://claw-agency.netlify.app

Je serais ravi d'organiser un audit gratuit de 30 minutes pour vous montrer exactement ce que nous pouvons faire pour {name}.

Disponible cette semaine ?

Cordialement,
Bernardo
Claw Agency — Luxembourg
claw.agency.hq@gmail.com
"""
        },
        "real_estate": {
            "subject": "Automatisation IA pour {name} — +50% de leads qualifiés",
            "body": """
Bonjour,

J'ai découvert {name} et je me permets de vous contacter avec une proposition concrète.

Chez Claw Agency, nous aidons les agences immobilières au Luxembourg à automatiser leur prospection et qualification de leads — sans changer leurs outils existants.

Ce que nous mettons en place pour vous :
- Scanner automatique de prospects acheteurs/vendeurs
- Qualification IA des leads entrants 24h/24
- Emails de suivi personnalisés automatiques
- Rapport quotidien des opportunités détectées

L'impact moyen pour nos clients :
→ +50% de leads qualifiés par mois
→ -4h de travail de prospection par jour
→ Réponse aux prospects en moins de 5 minutes

Vous pouvez voir nos services ici : https://claw-agency.netlify.app

Je serais ravi d'organiser un audit gratuit de 30 minutes.

Disponible cette semaine ?

Cordialement,
Bernardo
Claw Agency — Luxembourg
claw.agency.hq@gmail.com
"""
        }
    },
    "luxembourgish": {
        "dental": {
            "subject": "KI-Automatisatioun fir {name} — +40% Patienten ouni Méiaufwand",
            "body": """
Gudde Moien,

Ech hu {name} entdeckt an erlabe mir, Iech mat engem konkreten Virschlag ze kontaktéieren.

Bei Claw Agency hëllefe mir Dentalcliniken zu Lëtzebuerg, hir Prospektéierung an Kommunikatioun z'automatiséieren.

Wat mir fir Iech amisetzen:
- Automatesch Äntwerten op Rendez-vous-Ufroen 24/7
- Automatesch Patient-Follow-up per E-Mail/SMS
- Wëchentleche Leeschtungsbericht
- Méisproochege Chatbot fir Är Websäit

Duerchschnëttlech Impakt bei eise Clienten:
→ +40% méi Rendez-vous-Ufroen behandelt
→ -3 Stonnen administrativ Aarbecht pro Dag
→ Äntwert u Patienten a manner wéi 2 Minutten

Kuckt eis Servicer hei: https://claw-agency.netlify.app

Ech wier frou, en gratis 30-Minutten Audit ze organiseren.

Verfügbar dës Woch?

Mat beschte Gréiss,
Bernardo
Claw Agency — Lëtzebuerg
claw.agency.hq@gmail.com
"""
        }
    }
}

def detect_language(lead):
    """
    Detects language based on website domain or name.
    Default is French for Luxembourg.
    """
    notes = lead.get("notes", "").lower()
    name = lead.get("name", "").lower()
    
    # Check for .lu or Luxembourgish keywords
    lux_keywords = ["gudde moien", "lëtzebuerg", ".lu"]
    if any(kw in notes for kw in lux_keywords) or any(kw in name for kw in lux_keywords):
        return "luxembourgish"
    
    return "french"

def send_outreach_email(lead):
    """Sends a single outreach email via Resend."""
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL", "Claw Agency <onboarding@resend.dev>")
    
    if not api_key:
        log.error("RESEND_API_KEY not set")
        return False

    resend.api_key = api_key
    
    # Detect language and sector
    lang = detect_language(lead)
    sector = lead.get("sector", "dental")
    if sector not in ["dental", "real_estate"]:
        sector = "dental"

    # Fallback to French if Luxembourgish template missing for sector
    if lang not in TEMPLATES or sector not in TEMPLATES[lang]:
        lang = "french"
    
    template = TEMPLATES[lang][sector]
    subject = template["subject"].format(name=lead["name"])
    body = template["body"].format(name=lead["name"])

    try:
        log.info(f"Sending {lang} outreach to {lead['email']} ({lead['name']})")
        resend.Emails.send({
            "from": from_email,
            "to": lead["email"],
            "subject": subject,
            "text": body
        })
        
        # Log to database
        db.log_email_sent(lead["id"], subject, body)
        db.update_status(lead["id"], "sent")
        return True
    except Exception as e:
        log.error(f"Failed to send email to {lead['email']}: {e}")
        return False

def run_outreach_cycle():
    """Fetches new leads and sends outreach emails with a 5s delay."""
    leads = db.get_outreach_leads()
    sent_count = 0
    
    log.info(f"Starting outreach cycle for {len(leads)} leads")
    
    for lead in leads:
        if send_outreach_email(lead):
            sent_count += 1
            # Anti-spam delay
            time.sleep(2)
            
    return sent_count

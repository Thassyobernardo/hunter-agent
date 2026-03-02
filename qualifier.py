import os
import json
import logging
from groq import Groq, BadRequestError, APIStatusError, APIConnectionError

import database as db

log = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"
_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        _client = Groq(api_key=api_key)
    return _client


QUALIFICATION_PROMPT = """You are a senior automation consultant evaluating a client lead for a freelance agency.

Lead Source: {source}
Title: {title}
Description: {description}

Analyze this lead for automation potential and respond with ONLY a valid JSON object (no markdown, no extra text):
{{
  "problem_summary": "2-3 sentence summary of the client's core problem",
  "automation_solution": "specific automation solution you would build (be concrete)",
  "estimated_hours": <integer hours to build MVP>,
  "setup_fee": <integer USD for one-time setup>,
  "monthly_maintenance": <integer USD per month for ongoing support>,
  "client_roi": "quantified ROI estimate (e.g. saves 20h/month = $2000/month at $100/h)",
  "confidence": <integer 1-10 — how confident you are this is a real, winnable lead>
}}

Pricing guidelines:
- Simple automation (scripts, scraping, basic integrations): $500–$2000 setup, $100–$300/mo
- Medium (multi-step workflows, dashboards, APIs): $2000–$5000 setup, $300–$700/mo
- Complex (full systems, ML, multi-platform): $5000–$15000 setup, $700–$2000/mo

Confidence scoring:
- 8-10: Clear pain point, specific requirements, budget signals, automation is obvious fit
- 5-7: Good fit but vague requirements or unclear budget
- 1-4: Poor fit, no automation angle, or too vague to pursue"""


def qualify_lead(source: str, title: str, description: str) -> dict:
    try:
        resp = _get_client().chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": QUALIFICATION_PROMPT.format(
                    source=source,
                    title=title,
                    description=description[:3000]
                )
            }],
            temperature=0.3,
            max_tokens=768,
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)
    except BadRequestError as e:
        log.error("Groq 400 BadRequest in qualify_lead — status=%s message=%r body=%s",
                  e.status_code, e.message, e.body)
        return {"error": f"Groq 400: {e.message}", "confidence": 0}
    except APIStatusError as e:
        log.error("Groq API error in qualify_lead — status=%s message=%r body=%s",
                  e.status_code, e.message, e.body)
        return {"error": f"Groq {e.status_code}: {e.message}", "confidence": 0}
    except APIConnectionError as e:
        log.error("Groq connection error in qualify_lead: %s", e)
        return {"error": f"Groq connection error: {e}", "confidence": 0}
    except json.JSONDecodeError as e:
        log.error("Groq returned non-JSON in qualify_lead: %s", e)
        return {"error": "Groq response was not valid JSON", "confidence": 0}
    except Exception as e:
        log.error("Unexpected error in qualify_lead: %s", e, exc_info=True)
        return {"error": str(e), "confidence": 0}


def qualify_single(lead_id: int) -> dict:
    """Qualify one lead by ID. Saves result to DB and updates status. Returns qualification dict."""
    lead = db.get_lead(lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    result = qualify_lead(lead["source"], lead["title"], lead["description"] or "")
    db.save_qualification(lead_id, json.dumps(result))

    confidence = result.get("confidence", 0)
    new_status = "qualified" if confidence >= 6 else "skip"
    db.update_status(lead_id, new_status)

    log.info("Lead %d qualified — confidence=%s status=%s", lead_id, confidence, new_status)
    return result


def run_qualification() -> int:
    """Qualify all leads with status 'new'. Returns count of leads processed."""
    leads = db.get_leads(status="new")
    count = 0
    for lead in leads:
        try:
            qualify_single(lead["id"])
            count += 1
        except Exception as e:
            log.error("Failed to qualify lead %d: %s", lead["id"], e)
    log.info("Bulk qualification complete — %d leads processed", count)
    return count

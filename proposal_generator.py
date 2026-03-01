import os
import json
from groq import Groq

MODEL = "llama3-70b-8192"
_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        _client = Groq(api_key=api_key)
    return _client


ANALYSIS_PROMPT = """You are a senior software consultant analyzing a potential client lead.

Lead Source: {source}
Title: {title}
Description: {description}

Analyze this lead and respond with ONLY a valid JSON object (no markdown, no extra text):
{{
  "pain_points": ["list of identified pain points"],
  "tech_hints": ["any mentioned technologies or requirements"],
  "urgency": "low|medium|high",
  "budget_signal": "unknown|low|medium|high",
  "project_type": "one-line description of the project type",
  "ideal_solution": "brief description of the ideal solution",
  "estimated_complexity": "simple|medium|complex"
}}"""


PROPOSAL_PROMPT = """You are an expert freelancer writing a winning proposal. Be concise, human, and specific.

Lead Info:
- Source: {source}
- Title: {title}
- Description: {description}

Analysis:
{analysis}

Write a proposal with ONLY this JSON structure (no markdown, no extra text):
{{
  "hook": "1-2 sentences that prove you understand their exact problem",
  "solution": "2-3 sentences describing your specific approach and why it works",
  "tech_stack": "comma-separated list of technologies you'd use",
  "timeline": "realistic timeline estimate",
  "closing_question": "1 open-ended question that gets them talking",
  "upsell": "1 natural upsell opportunity that adds value"
}}

Rules:
- Sound like a real human, not a bot
- Reference specifics from their description
- Never use phrases like 'I hope this message finds you well'
- Be direct and confident"""


def analyze_lead(source: str, title: str, description: str) -> dict:
    try:
        resp = _get_client().chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": ANALYSIS_PROMPT.format(
                    source=source,
                    title=title,
                    description=description[:3000]
                )
            }],
            temperature=0.3,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        return {"error": str(e), "pain_points": [], "urgency": "unknown"}


def generate_proposal(source: str, title: str, description: str,
                      analysis: dict) -> dict:
    try:
        resp = _get_client().chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": PROPOSAL_PROMPT.format(
                    source=source,
                    title=title,
                    description=description[:3000],
                    analysis=json.dumps(analysis, indent=2)
                )
            }],
            temperature=0.7,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        return {"error": str(e), "hook": "Could not generate proposal."}


def process_lead(lead_id: int, source: str, title: str,
                 description: str) -> tuple[str, str]:
    """Returns (analysis_json, proposal_json) as strings."""
    analysis = analyze_lead(source, title, description)
    proposal = generate_proposal(source, title, description, analysis)
    return json.dumps(analysis), json.dumps(proposal)

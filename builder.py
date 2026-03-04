import os
import re
import json
import logging
import zipfile
from ai_utils import (
    MODEL, get_client, call_with_retry,
    BadRequestError, APIStatusError, APIConnectionError,
)

import database as db

log = logging.getLogger(__name__)

BUILDS_DIR = os.path.abspath(os.getenv("BUILDS_DIR", "builds"))


def _safe(s) -> str:
    """Escape braces in user-supplied strings so .format() won't choke."""
    return str(s or "").replace("{", "{{").replace("}", "}}")


def _slug(title: str, lead_id: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
    return f"{slug or 'project'}-{lead_id}"


def _parse_json_field(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _parse_files(raw: str) -> list[dict]:
    """Extract the JSON file list from Cerebras's response."""
    raw = raw.strip()
    # Strip markdown code fences if the model wrapped the output
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
    # Find the outermost JSON array in case there's stray text
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON array found in Cerebras response")
    return json.loads(raw[start : end + 1])


# ── Prompt ────────────────────────────────────────────────────────────────────

BUILD_PROMPT = """You are a senior Python developer. Generate a complete, production-ready automation project for a client.

## Client's Needs
**Problem:** {problem_summary}
**Solution to Build:** {automation_solution}
**Technologies:** {tech_hints}
**Scope:** ~{estimated_hours} hours

## Original Job Post
**Source:** {source}
**Title:** {title}
**Description:**
{description}

## Requirements
Generate WORKING Python code — no pseudocode, no "# TODO: implement this" stubs.
Every function must have a real implementation that solves the stated problem.

Files to include (at minimum):
1. `main.py` — entry point with `main()` and `if __name__ == "__main__": main()`
2. `requirements.txt` — pinned versions (e.g. `requests==2.31.0`)
3. `.env.example` — every required env var with inline comments
4. `README.md` — setup, configuration, and usage with examples

Add additional modules as needed (e.g. `scraper.py`, `processor.py`, `notifier.py`, `config.py`).

Code standards:
- Load config from environment variables via `python-dotenv`
- Use `logging` module (not bare `print` statements)
- Handle errors with specific exception types and meaningful messages
- Comment non-obvious logic

## Output Format
Return ONLY a valid JSON array. No markdown fences, no explanation text. Your response must begin with `[`.

Each element: {{"name": "relative/path/to/file.ext", "content": "complete file content"}}

Newlines in content must be written as \\n. Tabs as \\t. Backslashes as \\\\.

Example (abbreviated):
[
  {{"name": "main.py", "content": "import os\\nimport logging\\nfrom dotenv import load_dotenv\\n\\nload_dotenv()\\nlogging.basicConfig(level=logging.INFO)\\nlog = logging.getLogger(__name__)\\n\\ndef main():\\n    log.info('Starting...')\\n\\nif __name__ == '__main__':\\n    main()\\n"}},
  {{"name": "requirements.txt", "content": "requests==2.31.0\\npython-dotenv==1.0.0\\n"}},
  {{"name": ".env.example", "content": "# API key for the service\\nAPI_KEY=your_key_here\\n"}},
  {{"name": "README.md", "content": "# Automation Project\\n\\n## Setup\\n1. `pip install -r requirements.txt`\\n2. Copy `.env.example` to `.env` and fill in values\\n3. `python main.py`\\n"}}
]"""


# ── Core functions ────────────────────────────────────────────────────────────

def generate_project(lead: dict, qual: dict, proposal: dict, analysis: dict) -> list[dict]:
    """Call Cerebras to generate project files. Returns list of {name, content}."""
    tech_hints = ", ".join(analysis.get("tech_hints", []))
    if not tech_hints:
        tech_hints = proposal.get("tech_stack", "")
    if not tech_hints:
        tech_hints = "Python, requests, python-dotenv"

    problem_summary    = qual.get("problem_summary") or lead["title"]
    automation_solution = qual.get("automation_solution") or (lead.get("description") or "")[:500]
    estimated_hours    = qual.get("estimated_hours", "unknown")
    description        = (lead.get("description") or "")[:2000]

    prompt = BUILD_PROMPT.format(
        problem_summary=_safe(problem_summary),
        automation_solution=_safe(automation_solution),
        tech_hints=_safe(tech_hints),
        estimated_hours=_safe(estimated_hours),
        source=_safe(lead["source"]),
        title=_safe(lead["title"]),
        description=_safe(description),
    )

    raw = ""
    try:
        resp = call_with_retry(lambda: get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=8192,
        ))
        raw = resp.choices[0].message.content.strip()
        files = _parse_files(raw)
        files = [f for f in files if f.get("name") and f.get("content")]
        log.info("Cerebras generated %d files for lead %d", len(files), lead["id"])
        return files
    except BadRequestError as e:
        log.error("Cerebras 400 in generate_project — status=%s body=%s", e.status_code, e.body)
        raise
    except APIStatusError as e:
        log.error("Cerebras API error in generate_project — status=%s message=%r", e.status_code, e.message)
        raise
    except APIConnectionError as e:
        log.error("Cerebras connection error in generate_project: %s", e)
        raise
    except json.JSONDecodeError as e:
        log.error("Cerebras returned non-JSON: %s | Raw (first 500): %.500s", e, raw)
        raise RuntimeError(f"Cerebras response was not valid JSON: {e}") from e
    except ValueError as e:
        log.error("Could not locate JSON array in Cerebras response: %s | Raw (first 500): %.500s", e, raw)
        raise RuntimeError(str(e)) from e


def build_lead(lead_id: int) -> str:
    """
    Generate a complete project for a qualified lead and package it as a ZIP.
    Returns the absolute path to the ZIP file.
    """
    lead = db.get_lead(lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    qual     = _parse_json_field(lead.get("qualification"))
    proposal = _parse_json_field(lead.get("proposal"))
    analysis = _parse_json_field(lead.get("analysis"))

    log.info("Building project for lead %d: %s", lead_id, lead["title"])

    files = generate_project(lead, qual, proposal, analysis)
    if not files:
        raise RuntimeError("Cerebras returned an empty file list")

    os.makedirs(BUILDS_DIR, exist_ok=True)
    slug = _slug(lead["title"], lead_id)
    zip_path = os.path.join(BUILDS_DIR, f"{slug}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            archive_path = f"{slug}/{f['name'].lstrip('/')}"
            zf.writestr(archive_path, f["content"])
            
        # Add the INICIAR.bat file
        bat_content = (
            "@echo off\n"
            "echo =========================================\n"
            "echo      Iniciando seu Motor de Automacao     \n"
            "echo =========================================\n"
            "echo.\n"
            "echo 1. Instalando dependencias (Python)...\n"
            "pip install -r requirements.txt\n"
            "echo.\n"
            "echo 2. Executando o sistema principal...\n"
            "python main.py\n"
            "pause\n"
        )
        zf.writestr(f"{slug}/INICIAR.bat", bat_content)

    log.info("Packaged %d files (+ INICIAR.bat) → %s", len(files), zip_path)

    db.save_deliverable_path(lead_id, zip_path)
    db.update_status(lead_id, "built")

    return zip_path

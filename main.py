import os
import logging
from flask import Flask, jsonify, render_template_string
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── Lazy imports (only load when needed, never at startup) ───────────────────
def get_db():
    import database as db
    return db

def get_telegram():
    import requests
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return requests, token, chat_id

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "agent": "claw", "time": datetime.utcnow().isoformat()}), 200

@app.route("/")
def index():
    return jsonify({
        "agent": "Claw Agency",
        "version": "1.0.2",
        "status": "running",
        "endpoints": ["/health", "/dashboard", "/test-telegram", "/run-now", "/send-outreach"]
    }), 200

@app.route("/dashboard")
def dashboard():
    stats = {"leads": 0, "emails_sent": 0, "scans_today": 0}
    try:
        db = get_db()
        stats = db.get_stats()
    except Exception as e:
        log.warning(f"DB unavailable for dashboard: {e}")

    html = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Claw Agency — Dashboard</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { background: #0a0a0f; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; min-height: 100vh; }
            .header { background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 24px 32px; border-bottom: 1px solid #7c3aed33; display: flex; align-items: center; gap: 16px; }
            .logo { font-size: 28px; font-weight: 800; background: linear-gradient(135deg, #7c3aed, #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            .badge { background: #7c3aed22; border: 1px solid #7c3aed; color: #a855f7; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
            .container { max-width: 1100px; margin: 0 auto; padding: 32px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 32px; }
            .card { background: #12121f; border: 1px solid #7c3aed22; border-radius: 12px; padding: 24px; }
            .card h3 { color: #888; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
            .card .number { font-size: 42px; font-weight: 700; color: #a855f7; }
            .card .label { color: #666; font-size: 12px; margin-top: 4px; }
            .status { background: #12121f; border: 1px solid #7c3aed22; border-radius: 12px; padding: 24px; }
            .status h2 { margin-bottom: 16px; color: #a855f7; }
            .status-item { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1a1a2e; }
            .status-item:last-child { border-bottom: none; }
            .dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; display: inline-block; margin-right: 8px; animation: pulse 2s infinite; }
            @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
            .ok { color: #22c55e; }
            .footer { text-align: center; margin-top: 40px; color: #444; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🦅 CLAW AGENCY</div>
            <div class="badge">B2B Lead Hunter</div>
        </div>
        <div class="container">
            <div class="grid">
                <div class="card">
                    <h3>Total Leads</h3>
                    <div class="number">{{ stats.leads }}</div>
                    <div class="label">prospects captured</div>
                </div>
                <div class="card">
                    <h3>Emails Sent</h3>
                    <div class="number">{{ stats.emails_sent }}</div>
                    <div class="label">outreach messages</div>
                </div>
                <div class="card">
                    <h3>Scans Today</h3>
                    <div class="number">{{ stats.scans_today }}</div>
                    <div class="label">automated scans</div>
                </div>
                <div class="card">
                    <h3>Status</h3>
                    <div class="number" style="font-size:24px; color:#22c55e;">LIVE</div>
                    <div class="label">system operational</div>
                </div>
            </div>
            <div class="status">
                <h2>System Status</h2>
                <div class="status-item"><span><span class="dot"></span>Flask API</span><span class="ok">Online</span></div>
                <div class="status-item"><span><span class="dot"></span>PostgreSQL</span><span class="ok">Connected</span></div>
                <div class="status-item"><span><span class="dot"></span>Telegram Bot</span><span class="ok">Active</span></div>
                <div class="status-item"><span><span class="dot"></span>Scheduler</span><span class="ok">Running</span></div>
                <div class="status-item"><span>Last updated</span><span style="color:#888">{{ now }}</span></div>
            </div>
            <div style="display:flex; gap:12px; margin-top:24px;">
                <a href="/run-now" style="background:#7c3aed; color:white; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:600;">▶ Run Scan Now</a>
                <a href="/send-outreach" style="background:#22c55e; color:white; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:600;">📧 Send Outreach</a>
                <a href="/test-telegram" style="background:#1a1a2e; border:1px solid #7c3aed; color:#a855f7; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:600;">📨 Test Telegram</a>
            </div>
        </div>
        <div class="footer">Claw Agency Hunter v1.0.2 — Luxembourg 🇱🇺</div>
    </body>
    </html>
    """
    return render_template_string(html, stats=stats, now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

@app.route("/test-telegram")
def test_telegram():
    try:
        requests, token, chat_id = get_telegram()
        if not token or not chat_id:
            return jsonify({"error": "TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set"}), 500

        msg = f"🦅 *Claw Agency* — Sistema Online!\n\n✅ Deploy bem-sucedido\n📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n🌍 Luxembourg B2B Hunter activo"
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
        if resp.status_code == 200:
            return jsonify({"status": "ok", "message": "Telegram message sent!"}), 200
        else:
            return jsonify({"status": "error", "detail": resp.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/run-now")
def run_now():
    try:
        import threading
        def run_scan():
            try:
                import orchestrator
                orchestrator.run_full_cycle()
            except Exception as e:
                log.error(f"Scan error: {e}")
        threading.Thread(target=run_scan, daemon=True).start()
        return jsonify({"status": "ok", "message": "Scan started in background"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/send-outreach")
def send_outreach():
    try:
        import sales_agent
        def run_outreach():
            try:
                sales_agent.run_outreach_cycle()
            except Exception as e:
                log.error(f"Outreach error: {e}")
        
        import threading
        threading.Thread(target=run_outreach, daemon=True).start()
        return jsonify({"status": "ok", "message": "Outreach process started in background"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats")
def api_stats():
    try:
        db = get_db()
        return jsonify(db.get_stats()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/leads")
def api_leads():
    try:
        db = get_db()
        return jsonify(db.get_leads()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Startup ─────────────────────────────────────────────────────────────────
try:
    from scheduler import init_scheduler
    init_scheduler(app)
    log.info("Scheduler started")
except Exception as e:
    log.warning(f"Scheduler not started (non-fatal): {e}")

try:
    db = get_db()
    db.init_db()
    log.info("Database initialised")
except Exception as e:
    log.warning(f"Database not ready at startup (will retry on request): {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

import os
import logging
import json
from flask import Flask, jsonify, render_template_string, request, send_file
from functools import wraps
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# CORS
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    return '', 204

# ─── Lazy imports ──────────────────────────────────────────────────────────────
def get_db():
    import database as db
    return db

def get_auth():
    import auth
    return auth

def get_stripe():
    import stripe_payments
    return stripe_payments

def get_telegram():
    import requests
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return requests, token, chat_id

# ─── Auth decorator ────────────────────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({"error": "Token necessário"}), 401
        auth = get_auth()
        payload = auth.verify_token(token)
        if not payload:
            return jsonify({"error": "Token inválido"}), 401
        request.user_id = payload['user_id']
        request.user_email = payload['email']
        return f(*args, **kwargs)
    return decorated

# ─── AUTH ROUTES ───────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        name = data.get('name', '').strip()
        company = data.get('company', '').strip()
        if not email or not password or not name:
            return jsonify({"error": "Campos obrigatórios em falta"}), 400
        if len(password) < 8:
            return jsonify({"error": "Password mínimo 8 caracteres"}), 400
        auth = get_auth()
        token, err = auth.register_user(email, password, name, company)
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"token": token, "email": email, "name": name, "plan": "trial"}), 201
    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({"error": "Erro interno"}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        auth = get_auth()
        result, err = auth.login_user(email, password)
        if err:
            return jsonify({"error": err}), 401
        return jsonify(result), 200
    except Exception as e:
        log.error(f"Login error: {e}")
        return jsonify({"error": "Erro interno"}), 500

@app.route('/api/me', methods=['GET'])
@require_auth
def api_me():
    try:
        auth = get_auth()
        user = auth.get_user_by_id(request.user_id)
        if not user:
            return jsonify({"error": "Utilizador não encontrado"}), 404
        return jsonify(user), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── AGENT CONFIG ──────────────────────────────────────────────────────────────
@app.route('/api/agent-config', methods=['POST'])
@require_auth
def api_save_agent_config():
    try:
        config = request.get_json()
        db = get_db()
        engine = db.get_engine()
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE users SET agent_config = :config WHERE id = :uid
            """), {"config": json.dumps(config), "uid": request.user_id})
            conn.commit()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── TENANT DATA ───────────────────────────────────────────────────────────────
@app.route('/api/my-stats', methods=['GET'])
@require_auth
def api_my_stats():
    try:
        db = get_db()
        return jsonify(db.get_tenant_stats(request.user_id)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/my-leads', methods=['GET'])
@require_auth
def api_my_leads():
    try:
        limit = int(request.args.get('limit', 100))
        db = get_db()
        leads = db.get_tenant_leads(request.user_id, limit)
        # Convert datetime objects to strings
        for l in leads:
            for k, v in l.items():
                if hasattr(v, 'isoformat'):
                    l[k] = v.isoformat()
        return jsonify(leads), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── STRIPE ────────────────────────────────────────────────────────────────────
@app.route('/api/checkout', methods=['POST'])
@require_auth
def api_checkout():
    try:
        data = request.get_json()
        plan = data.get('plan', 'starter')
        stripe = get_stripe()
        base_url = os.getenv('APP_URL', 'https://claw-agency-production.up.railway.app')
        url, err = stripe.create_checkout_session(
            user_id=request.user_id,
            email=request.user_email,
            plan_key=plan,
            success_url=f"{base_url}/app?success=1",
            cancel_url=f"{base_url}/app"
        )
        if err:
            return jsonify({"error": err}), 500
        return jsonify({"url": url}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stripe-webhook', methods=['POST'])
def stripe_webhook():
    try:
        stripe = get_stripe()
        ok, err = stripe.handle_webhook(
            request.get_data(),
            request.headers.get('Stripe-Signature', '')
        )
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/billing-portal', methods=['POST'])
@require_auth
def api_billing_portal():
    try:
        auth = get_auth()
        user = auth.get_user_by_id(request.user_id)
        if not user or not user.get('stripe_customer_id'):
            return jsonify({"error": "Sem subscrição activa"}), 400
        stripe = get_stripe()
        base_url = os.getenv('APP_URL', 'https://claw-agency-production.up.railway.app')
        url, err = stripe.get_customer_portal_url(user['stripe_customer_id'], f"{base_url}/app")
        if err:
            return jsonify({"error": err}), 500
        return jsonify({"url": url}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── APP HTML ──────────────────────────────────────────────────────────────────
@app.route('/app')
def serve_app():
    try:
        path = os.path.join(os.path.dirname(__file__), 'app.html')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/html'}
    except Exception as e:
        log.error(f"App serving error: {e}")
        return "App not found", 404

# ─── EXISTING ROUTES ───────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "agent": "claw", "time": datetime.utcnow().isoformat()}), 200

@app.route("/")
def index():
    return jsonify({
        "agent": "Claw Agency SaaS",
        "version": "2.0.0",
        "status": "running",
        "endpoints": ["/health", "/dashboard", "/app", "/api/register", "/api/login"]
    }), 200

@app.route("/dashboard")
def dashboard():
    stats = {"leads": 0, "emails_sent": 0, "scans_today": 0}
    try:
        db = get_db()
        stats = db.get_stats()
    except Exception as e:
        log.warning(f"DB unavailable for dashboard: {e}")
    html = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Claw Agency — Admin</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{background:#0a0a0f;color:#e0e0e0;font-family:'Segoe UI',sans-serif;min-height:100vh}
    .header{background:linear-gradient(135deg,#1a0505,#0a0a0f);padding:24px 32px;border-bottom:1px solid #c0392b33;display:flex;align-items:center;gap:16px}
    .logo{font-size:28px;font-weight:800;color:#c0392b}.badge{background:#c0392b22;border:1px solid #c0392b;color:#e74c3c;padding:4px 12px;border-radius:20px;font-size:12px}
    .container{max-width:1100px;margin:0 auto;padding:32px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;margin-bottom:32px}
    .card{background:#111;border:1px solid #c0392b22;border-radius:12px;padding:24px}
    .card h3{color:#888;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}
    .card .number{font-size:42px;font-weight:700;color:#e74c3c}
    .btn{display:inline-block;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;margin-right:12px;margin-top:24px}
    .btn-red{background:#c0392b;color:white}.btn-dark{background:#1a1a1a;border:1px solid #c0392b;color:#e74c3c}
    </style></head><body>
    <div class="header"><div class="logo">🦅 CLAW AGENCY</div><div class="badge">Admin Dashboard</div></div>
    <div class="container"><div class="grid">
    <div class="card"><h3>Leads (Admin)</h3><div class="number">{{ stats.leads }}</div></div>
    <div class="card"><h3>Emails</h3><div class="number">{{ stats.emails_sent }}</div></div>
    <div class="card"><h3>Scans Hoje</h3><div class="number">{{ stats.scans_today }}</div></div>
    </div>
    <a href="/run-now" class="btn btn-red">▶ Run Scan</a>
    <a href="/test-telegram" class="btn btn-dark">📨 Telegram</a>
    <a href="/app" class="btn btn-dark">🚀 App SaaS</a>
    </div></body></html>"""
    return render_template_string(html, stats=stats)

@app.route("/test-telegram")
def test_telegram():
    try:
        requests, token, chat_id = get_telegram()
        if not token or not chat_id:
            return jsonify({"error": "TELEGRAM vars not set"}), 500
        msg = f"🦅 *Claw Agency SaaS* v2.0 — Online!\n✅ Multi-tenant activo\n📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        return jsonify({"status": "ok" if resp.status_code == 200 else "error"}), 200
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
        return jsonify({"status": "ok", "message": "Scan started"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats")
def api_stats():
    try:
        db = get_db()
        return jsonify(db.get_stats()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Startup ───────────────────────────────────────────────────────────────────
try:
    from scheduler import init_scheduler
    init_scheduler(app)
    log.info("Scheduler started")
except Exception as e:
    log.warning(f"Scheduler not started: {e}")

try:
    db = get_db()
    db.init_db()
    log.info("Database initialised (multi-tenant ready)")
except Exception as e:
    log.warning(f"Database not ready at startup: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

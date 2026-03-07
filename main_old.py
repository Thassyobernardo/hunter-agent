import os
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Load env before other imports
load_dotenv()

import database as db
import orchestrator
import schemas

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
)
log = logging.getLogger("ClawAPI")

app = FastAPI(
    title="Claw Agency API",
    description="Autonomous Multi-Agent Lead Generation System",
    version="2.0.0"
)

# --- Startup ---
@app.on_event("startup")
async def startup_event():
    db.init_db()
    log.info("Database initialized and FastAPI started.")
    
    # Run the startup orchestrator cycle in the background
    asyncio.create_task(run_startup_cycle())

async def run_startup_cycle():
    """Initial cycle with a delay to allow deployment stabilization."""
    log.info("Startup: Orchestrator will run in 10 seconds...")
    await asyncio.sleep(10)
    try:
        # Reset leads (optional, could be move to a task)
        import reset_skipped
        reset_skipped.reset_skipped_leads()
        
        log.info("Startup: Running initial multi-agent cycle...")
        orchestrator.run_full_agency_cycle()
    except Exception as e:
        log.error(f"Startup cycle failed: {e}")

# --- API Routes ---

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/stats", response_model=schemas.StatsResponse)
async def get_stats():
    return db.get_stats()

@app.get("/api/leads", response_model=List[schemas.LeadResponse])
async def get_leads(
    status: Optional[str] = None, 
    source: Optional[str] = None, 
    limit: int = 50, 
    offset: int = 0
):
    return db.get_leads(status=status, source=source, limit=limit, offset=offset)

@app.get("/api/leads/{lead_id}", response_model=schemas.LeadResponse)
async def get_lead(lead_id: int):
    lead = db.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@app.patch("/api/leads/{lead_id}/status")
async def update_lead_status(lead_id: int, req: schemas.UpdateStatusRequest):
    try:
        db.update_status(lead_id, req.status)
        return {"ok": True, "lead_id": lead_id, "status": req.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Manually trigger the LangGraph orchestration cycle."""
    background_tasks.add_task(orchestrator.run_full_agency_cycle)
    return {"ok": True, "message": "Agency cycle triggered in background."}

@app.get("/api/leads/{lead_id}/download")
async def download_lead(lead_id: int):
    lead = db.get_lead(lead_id)
    if not lead or not lead.get("deliverable_path"):
        raise HTTPException(status_code=404, detail="Deliverable not found")
    
    path = lead["deliverable_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File missing on disk")
        
    return FileResponse(
        path, 
        media_type="application/zip", 
        filename=os.path.basename(path)
    )

# --- Legacy Dashboard Support ---
# For now, we keep the dashboard as static or simple HTML if needed.
# Since the user still wants the dashboard, we serve it via FastAPI.
# Note: This might require moving templates/ to a folder FastAPI can see.

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Claw Agency API is running. Visit /docs for documentation."}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

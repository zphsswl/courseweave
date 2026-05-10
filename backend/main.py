from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.database import init_db
from backend.api import textbooks, jobs, graph, rag, chat, report, benchmark, model_status, system, integration
from backend.config import get_model_status
import os

app = FastAPI(title="MedEssence Agent - 七书归一", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(textbooks.router)
app.include_router(jobs.router)
app.include_router(graph.router)
app.include_router(rag.router)
app.include_router(chat.router)
app.include_router(report.router)
app.include_router(benchmark.router)
app.include_router(model_status.router)
app.include_router(system.router)
app.include_router(integration.router)

@app.on_event("startup")
def startup():
    os.makedirs("data", exist_ok=True)
    init_db()

@app.get("/api/health")
def health():
    status = get_model_status()
    return {
        "status": "ok",
        "name": "MedEssence Agent",
        "version": "1.1.0",
        "model": {
            "provider": status["provider"],
            "model": status["model"],
            "api_key_configured": status["api_key_configured"],
        }
    }

# Serve frontend static files in production
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

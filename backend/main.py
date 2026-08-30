from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.database import init_db
from backend.api import textbooks, jobs, graph, rag, chat, report, benchmark, model_status, system, integration, courses, alignment, agent
from backend.config import get_model_status, CORS_ORIGINS, PUBLIC_DEMO_READ_ONLY, SEED_DEMO_DATA
import os

app = FastAPI(title="CourseWeave - 教材知识网络", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

READ_ONLY_ALLOWED_POSTS = {"/api/rag/query", "/api/rag/node-query"}


@app.middleware("http")
async def protect_public_demo(request: Request, call_next):
    """Keep the hosted portfolio demo useful without exposing destructive or costly writes."""
    if (
        PUBLIC_DEMO_READ_ONLY
        and request.method in {"POST", "PATCH", "PUT", "DELETE"}
        and request.url.path not in READ_ONLY_ALLOWED_POSTS
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "在线作品为只读演示；请在本地运行后体验上传、抽取与审核。"},
        )
    return await call_next(request)

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
app.include_router(courses.router)
app.include_router(alignment.router)
app.include_router(agent.router)

@app.on_event("startup")
def startup():
    os.makedirs("data", exist_ok=True)
    init_db()
    if SEED_DEMO_DATA:
        from backend.services.demo_seed import seed_demo_course
        seed_demo_course()
    from backend.services.job_queue import start_job_worker
    start_job_worker()

@app.get("/api/health")
def health():
    status = get_model_status()
    return {
        "status": "ok",
        "name": "CourseWeave",
        "version": "1.2.0",
        "public_demo_read_only": PUBLIC_DEMO_READ_ONLY,
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
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port)

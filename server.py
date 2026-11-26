"""
Web server for the Requirements Engineering & SDLC Detection Assistant.

Thin FastAPI layer over the multi-agent code in src/.
Serves the punk frontend from ./web and exposes a small JSON API.

Run:  python -m uvicorn server:app --reload --port 8000
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import settings

logger = logging.getLogger("server")

WEB_DIR = Path(__file__).resolve().parent / "web"
SAMPLES_DIR = settings.BASE_DIR / "sample_inputs"

app = FastAPI(title="REQ//PUNK", version="1.0.0")

# Heavy objects (embedding model, chroma, cross-encoder) are built once, lazily.
_lock = threading.Lock()
_orchestrator = None
_pipeline = None


def get_orchestrator():
    global _orchestrator, _pipeline
    with _lock:
        if _orchestrator is None:
            from src.orchestrator import Orchestrator

            _orchestrator = Orchestrator()
            _pipeline = _orchestrator.rag
        return _orchestrator


def get_pipeline():
    get_orchestrator()
    return _pipeline


def slugify(title: str) -> str:
    # Must match Orchestrator.run() so we can find the file it saved.
    return title.lower().replace(" ", "_").replace("-", "_")[:40]


def _safe_slug(slug: str) -> str:
    if not slug or any(c in slug for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Invalid report name")
    return slug


# ----------------------------------------------------------------- models


class AnalyzeRequest(BaseModel):
    title: str = "Untitled Project"
    text: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    source_type: Optional[str] = None


class IngestRequest(BaseModel):
    force: bool = False


# -------------------------------------------------------------------- api


@app.get("/api/status")
def status():
    out_dir = Path(settings.OUTPUT_DIR)
    return {
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.OLLAMA_MODEL if settings.LLM_PROVIDER in ("ollama", "fallback") else (
            settings.OPENAI_MODEL if settings.LLM_PROVIDER == "openai" else settings.GEMINI_MODEL
        ),
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
        "reranker": settings.CROSS_ENCODER_MODEL_NAME,
        "rag_docs": len(list(Path(settings.RAG_DOCS_DIR).glob("*.txt"))),
        "reports": len(list(out_dir.glob("*_report.json"))) if out_dir.exists() else 0,
        "engine_loaded": _orchestrator is not None,
    }


@app.get("/api/samples")
def samples():
    items = []
    if SAMPLES_DIR.exists():
        for p in sorted(SAMPLES_DIR.glob("*.md")) + sorted(SAMPLES_DIR.glob("*.txt")):
            items.append(
                {
                    "name": p.stem,
                    "title": p.stem.replace("_", " ").title(),
                    "text": p.read_text(encoding="utf-8"),
                }
            )
    return items


@app.get("/api/reports")
def list_reports():
    out_dir = Path(settings.OUTPUT_DIR)
    rows = []
    if out_dir.exists():
        for p in out_dir.glob("*_report.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                rows.append(
                    {
                        "slug": p.stem.removesuffix("_report"),
                        "title": d.get("project_title", p.stem),
                        "timestamp": d.get("timestamp", ""),
                        "model": d["sdlc_recommendation"]["recommended_model"],
                        "confidence": d["sdlc_recommendation"]["confidence"],
                        "requirements": len(d["requirements_analysis"]["requirements"]),
                    }
                )
            except Exception as e:  # skip corrupt / foreign files
                logger.warning("Skipping %s: %s", p.name, e)
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


@app.get("/api/reports/{slug}")
def get_report(slug: str):
    slug = _safe_slug(slug)
    p = Path(settings.OUTPUT_DIR) / f"{slug}_report.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    title = (req.title or "Untitled Project").strip() or "Untitled Project"
    orch = get_orchestrator()
    try:
        started = datetime.now()
        report = orch.run(stakeholder_input=req.text, project_title=title, save_outputs=True)
        elapsed = (datetime.now() - started).total_seconds()
    except ValueError as e:  # validate_input errors (too short, etc.)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")
    data = report.model_dump(mode="json")
    data["_slug"] = slugify(title)
    data["_elapsed_seconds"] = round(elapsed, 1)
    return data


@app.post("/api/search")
def search(req: SearchRequest):
    q = req.query.strip()
    if len(q) < 3:
        raise HTTPException(status_code=422, detail="Query too short")
    pipe = get_pipeline()
    try:
        hits = pipe.retrieve(q, top_k=max(1, min(req.top_k, 10)), source_type_filter=req.source_type or None)
    except Exception as e:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")
    return [
        {
            "doc_id": c.get("doc_id", ""),
            "doc_name": c.get("doc_name", ""),
            "source_type": c.get("source_type", ""),
            "section_title": c.get("section_title", ""),
            "clause_id": c.get("clause_id", ""),
            "content": c.get("content", ""),
            "score": round(float(score), 4),
        }
        for c, score in hits
    ]


@app.post("/api/evaluate")
def evaluate():
    from src.rag.evaluation import RetrievalEvaluator

    pipe = get_pipeline()
    try:
        return RetrievalEvaluator().evaluate_pipeline(pipe)
    except Exception as e:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")


@app.post("/api/ingest")
def ingest(req: IngestRequest):
    pipe = get_pipeline()
    try:
        return pipe.ingest_documents(force=req.force)
    except Exception as e:
        logger.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")


# --------------------------------------------------------------- frontend


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

"""
DegreeCheck — FastAPI backend
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import audit, transcript, programs, timeline

app = FastAPI(title="DegreeCheck API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit.router,      prefix="/audit",      tags=["Audit"])
app.include_router(transcript.router, prefix="/transcript",  tags=["Transcript"])
app.include_router(programs.router,   prefix="/programs",    tags=["Programs"])
app.include_router(timeline.router,   prefix="/timeline",    tags=["Timeline"])


@app.get("/health")
def health():
    return {"status": "ok"}

"""
DegreeCheck — FastAPI backend
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from routers import audit, transcript, programs, timeline, admin, users, courses

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
app.include_router(users.router,      prefix="/users",       tags=["Users"])
app.include_router(admin.router,      prefix="/admin",       tags=["Admin"])
app.include_router(courses.router,    prefix="/courses",     tags=["Courses"])

# Serve static assets (admin dashboard HTML)
_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}

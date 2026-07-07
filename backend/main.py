"""
DegreeCheck — FastAPI backend
"""

import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from deps import require_admin
from routers import audit, transcript, programs, timeline, admin, users, courses

app = FastAPI(title="DegreeCheck API", version="0.1.0")

# Comma-separated allowlist from the environment. Defaults to common Expo dev
# origins so local development works out of the box; set CORS_ORIGINS in prod.
_default_origins = "http://localhost:8081,http://localhost:8082,http://localhost:19006"
_cors_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit.router,      prefix="/audit",      tags=["Audit"])
app.include_router(transcript.router, prefix="/transcript",  tags=["Transcript"])
app.include_router(programs.router,   prefix="/programs",    tags=["Programs"])
app.include_router(timeline.router,   prefix="/timeline",    tags=["Timeline"])
app.include_router(users.router,      prefix="/users",       tags=["Users"])
app.include_router(admin.router,      prefix="/admin",       tags=["Admin"],
                   dependencies=[Depends(require_admin)])
app.include_router(courses.router,    prefix="/courses",     tags=["Courses"])

# Serve static assets (admin dashboard HTML)
_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}

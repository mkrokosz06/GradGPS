"""
DegreeCheck — FastAPI backend
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from routers import audit, transcript, programs, timeline, admin, users, courses, session, support, email_auth, config, user_choices, substitutions

app = FastAPI(title="DegreeCheck API", version="0.1.0")

# Comma-separated allowlist from the environment. Defaults to common Expo dev
# origins so local development works out of the box; set CORS_ORIGINS in prod.
_default_origins = "http://localhost:8081,http://localhost:8082,http://localhost:19006"
_cors_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]
# The marketing site's contact form posts here from the browser — always allow
# it, independent of whatever CORS_ORIGINS is set to in the environment.
for _site in ("https://gradgps.com", "https://www.gradgps.com"):
    if _site not in _cors_origins:
        _cors_origins.append(_site)

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
app.include_router(admin.router,      prefix="/admin",       tags=["Admin"])
app.include_router(courses.router,    prefix="/courses",     tags=["Courses"])
app.include_router(session.router,    prefix="/auth",        tags=["Auth"])
app.include_router(email_auth.router, prefix="/auth",        tags=["Auth"])
app.include_router(support.router,    prefix="/support",     tags=["Support"])
app.include_router(config.router,     prefix="/config",      tags=["Config"])
app.include_router(user_choices.router, prefix="/user-choices", tags=["User Choices"])
app.include_router(substitutions.router, prefix="/substitutions", tags=["Substitutions"])

# Charlie (multi-school "add my school" agent) is dormant unless explicitly
# enabled. It stays OFF in production: the router is never imported or mounted,
# so there are no /charlie routes and no dependency on the school_requests table
# (which prod's DynamoDB + IAM role don't provide). Set CHARLIE_ENABLED=1 in
# backend/.env for local development to work on it.
if os.getenv("CHARLIE_ENABLED") == "1":
    from routers import charlie
    app.include_router(charlie.router, prefix="/charlie", tags=["Charlie"])

# Serve static assets (admin dashboard HTML)
_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}

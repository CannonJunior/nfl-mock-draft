"""
NFL Mock Draft 2026 — FastAPI application entry point.

Runs on port 8988. All configuration is loaded from environment
variables via python-dotenv.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import router
from app.api.scrape import scrape_router
from app.api.predictions import predictions_router

# Load .env file if present
load_dotenv()

# Configuration from environment (with safe defaults)
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8988"))
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(
    title="NFL Mock Draft 2026",
    description="Predicting selections in the 2026 NFL Draft — Rounds 1-3",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Mount static file directory for CSS, JS, and images
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register all page and API routes
app.include_router(router)
app.include_router(scrape_router)
app.include_router(predictions_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level="info",
    )

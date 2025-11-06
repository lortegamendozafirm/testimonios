# src/main.py
from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.logging_conf import bootstrap_logging_from_env, get_logger
from src.settings import get_settings

# Routers
from src.api.health import router as health_router
from src.api.testimonios import router as testimonios_router

# Middleware global (si es función tipo decorator HTTP middleware)
# Si en tu proyecto es una clase de Starlette, cámbialo por add_middleware(ClaseMiddleware)
try:
    from src.api.middleware.error_handler import unhandled_exception_middleware
    _HAS_ERR_MW = True
except Exception:
    unhandled_exception_middleware = None  # opcional
    _HAS_ERR_MW = False

# --- App ---
bootstrap_logging_from_env()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title="testimonios",
    version=os.getenv("APP_VERSION", "1.0.0"),
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS (ajústalo a tus dominios en prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware global de errores/logs (si es un http-middleware function)
if _HAS_ERR_MW and callable(unhandled_exception_middleware):
    app.middleware("http")(unhandled_exception_middleware)

# Warnings de configuración (no detienen arranque)
for w in settings.sanity_warnings():
    logger.warning(w)

# Routers
app.include_router(health_router, tags=["health"])
app.include_router(testimonios_router, tags=["testimonios"])

# Endpoint raíz simple (opcional)
@app.get("/")
def root():
    return {
        "ok": True,
        "service": "testimonios",
        "project": settings.project_id,
        "region": settings.region,
        "adc": "cloud_run_adc" if settings.is_cloud_run else "local_sa_file",
    }

# Para ejecutar directamente `python -m src.main` si quieres.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)), reload=True)

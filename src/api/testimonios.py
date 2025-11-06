# src/api/testimonios.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.logging_conf import bootstrap_logging_from_env, get_logger
from src.settings import get_settings
from src.domain.schemas import TestimonyRequest, TestimonyResponse
from src.orchestration.runner import run_testimony

# Inicializa logging desde env (json/text, nivel, pii)
bootstrap_logging_from_env()
logger = get_logger(__name__)
settings = get_settings()

# Loguea advertencias de configuración (no detiene el arranque)
for w in settings.sanity_warnings():
    logger.warning(w)

router = APIRouter()

@router.post(
    "/generate-testimony",
    response_model=TestimonyResponse,
    summary="Genera testimonio a partir de transcript (Docs o raw_text) y crea SIEMPRE un Doc nuevo",
)
async def generate_testimony(payload: TestimonyRequest):
    """
    Precedencia de fuente: raw_text > transcription_doc_id > transcription_link.
    Crea SIEMPRE un Google Doc nuevo en OUTPUT_DRIVE_FOLDER_ID (o output_folder_id si viene en el request).
    """
    try:
        result = run_testimony(payload)  # devuelve dict compatible con TestimonyResponse
        return result
    except HTTPException:
        # Ya viene mapeado con status/detail accionables
        raise
    except Exception as e:
        logger.exception("Unhandled error in /generate-testimony", extra={"case_id": payload.case_id})
        raise HTTPException(status_code=500, detail="Error interno inesperado.")

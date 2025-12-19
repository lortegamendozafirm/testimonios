# src/api/testimonios.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from src.logging_conf import bootstrap_logging_from_env, get_logger
from src.settings import get_settings
from src.domain.schemas import TestimonyRequest, TestimonyResponse

# Importamos la función principal del runner
from src.orchestration.runner import run_testimony

bootstrap_logging_from_env()
logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()

@router.post(
    "/generate-testimony",
    response_model=TestimonyResponse,
    summary="Endpoint manual/directo para generar testimonios",
)
async def generate_testimony_endpoint(payload: TestimonyRequest):
    """
    Endpoint estándar.
    """
    try:
        return run_testimony(payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en /generate-testimony", extra={"case_id": payload.case_id})
        raise HTTPException(status_code=500, detail="Error interno inesperado.")

@router.post(
    "/webhook/chain",
    response_model=TestimonyResponse,
    summary="Endpoint para encadenamiento automático (Llamado por el Transcriptor/Enqueuer)",
)
async def webhook_chain_endpoint(payload: TestimonyRequest):
    """
    Recibe el payload combinado (Template de Apps Script + Resultado de Transcripción).
    Como el payload es plano, Pydantic lo parsea automáticamente a TestimonyRequest:
    - payload.transcription_doc_id: Se llena automáticamente.
    - payload.sheet_callback: Se llena automáticamente si viene en el JSON.
    """
    logger.info(f"🔗 Webhook Chain recibido para Caso: {payload.case_id}")
    try:
        return run_testimony(payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en /webhook/chain", extra={"case_id": payload.case_id})
        raise HTTPException(status_code=500, detail="Error interno en cadena de testimonios.")
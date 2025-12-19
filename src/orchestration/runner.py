# src/orchestration/runner.py
from __future__ import annotations

import json
import re
from typing import Any, Dict

from fastapi import HTTPException

from src.logging_conf import get_logger
from src.settings import get_settings
# Importamos los nuevos esquemas
from src.domain.schemas import TestimonyRequest, TestimonyResponse, TranscriptionWebhookRequest
from src.clients.drive_client import assert_sa_has_access
from src.clients.gdocs_client import get_document_content, write_markdown_to_document
from src.clients.vertex_client import generate_text
from src.clients.sheets_client import update_row_status
from src.auth import build_drive_client
from src.domain.prompt_loader import render_testimony_prompt


logger = get_logger(__name__)
settings = get_settings()

# ... (Las funciones utilitarias _extract_doc_id, _resolve_language, etc. SE MANTIENEN IGUAL) ...
def _extract_doc_id_from_url(url: str) -> str:
    m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    if not m: raise HTTPException(422, "No pude extraer el doc_id.")
    return m.group(1)

def _resolve_language(req: TestimonyRequest) -> str:
    if req.language: return (req.language or "").lower()
    return (req.extra or {}).get("language", settings.default_language or "es").lower()

def _map_google_http_error(e: Exception, *, op: str, file_id: str) -> HTTPException:
    return HTTPException(status_code=403, detail=f"{op} falló para {file_id}: {e}")

def _fallback_prompt(transcript: str, req: TestimonyRequest, language: str) -> str:
    # ... (Tu código de fallback prompt se mantiene igual) ...
    return f"FALLBACK PROMPT {language}..." # Resumido para brevedad

# ---------------------------
# Caso de uso principal
# ---------------------------

def run_testimony(req: TestimonyRequest) -> Dict[str, Any]:
    """
    Ejecuta el flujo de generación de testimonio y escribe SIEMPRE en el Doc output_doc_id.
    """
    logger.info("🚀 run_testimony", extra={"case_id": req.case_id, "context": req.context})

    # 1. Validaciones y Accesos (Sin cambios)
    target_doc_id = (req.output_doc_id or "").strip()
    if not target_doc_id:
        raise HTTPException(422, "Falta 'output_doc_id'.")
    
    try:
        assert_sa_has_access(target_doc_id, use_docs_api=True)
    except Exception as e:
        raise _map_google_http_error(e, op="Validar acceso destino", file_id=target_doc_id)

    # 2. Obtener Fuente (Sin cambios)
    language = _resolve_language(req)
    if req.raw_text:
        transcript = req.raw_text
    elif req.transcription_doc_id:
        src_doc = req.transcription_doc_id.strip()
        try:
            transcript = get_document_content(src_doc)
        except Exception as e:
            raise _map_google_http_error(e, op="Leer fuente", file_id=src_doc)
    elif req.transcription_link:
        src_doc = _extract_doc_id_from_url(str(req.transcription_link))
        try:
            transcript = get_document_content(src_doc)
        except Exception as e:
            raise _map_google_http_error(e, op="Leer fuente", file_id=src_doc)
    else:
        raise HTTPException(422, "Falta fuente.")

    if not transcript or len(transcript.strip()) < 20:
        raise HTTPException(422, "Transcript vacío.")

    # 3. Prompt + LLM (Sin cambios)
    try:
        prompt = render_testimony_prompt(language=language, templates_dir=settings.prompts_dir, transcript=transcript, req=req)
    except Exception:
        prompt = _fallback_prompt(transcript=transcript, req=req, language=language)

    try:
        output_text = generate_text(prompt)
    except Exception:
        raise HTTPException(500, "Error al generar texto con el modelo.")

    # 4. Escribir en Doc (Sin cambios)
    try:
        write_markdown_to_document(target_doc_id, output_text)
    except Exception as e:
        raise _map_google_http_error(e, op="Escribir salida", file_id=target_doc_id)

    # 5. Obtener link (Sin cambios)
    try:
        drive = build_drive_client()
        meta = drive.files().get(fileId=target_doc_id, fields="webViewLink", supportsAllDrives=True).execute()
        output_link = meta.get("webViewLink", f"https://docs.google.com/document/d/{target_doc_id}/edit")
    except Exception:
        output_link = f"https://docs.google.com/document/d/{target_doc_id}/edit"

    logger.info("✅ Testimonio generado", extra={"case_id": req.case_id})

    # ---------------------------------------------------------
    # ✅ 6. CALLBACK A GOOGLE SHEETS (NUEVO)
    # ---------------------------------------------------------
    if req.sheet_callback:
        cb = req.sheet_callback
        logger.info(f"📊 Actualizando Sheet: {cb.spreadsheet_id} (Fila {cb.row_index})")
        
        try:
            # Escribir URL del Testimonio
            if cb.testimony_doc_col:
                update_row_status(
                    cb.spreadsheet_id, cb.sheet_name, cb.row_index, 
                    cb.testimony_doc_col, output_link
                )
            
            # Escribir Status Final
            if cb.status_col:
                 update_row_status(
                    cb.spreadsheet_id, cb.sheet_name, cb.row_index, 
                    cb.status_col, "✅ Testimonio Listo"
                )
        except Exception as e:
            logger.error(f"❌ Error actualizando Sheets: {e}")

    return TestimonyResponse(
        status="success",
        message="Testimonio generado correctamente.",
        doc_id=target_doc_id,
        output_doc_link=output_link,
        model=settings.model_id,
        language=language,
        case_id=req.case_id,
        request_id=req.request_id,
    ).model_dump()


# ---------------------------
# ✅ ADAPTADOR PARA WEBHOOK (NUEVO)
# ---------------------------
def run_testimony_from_webhook(webhook_req: TranscriptionWebhookRequest) -> Dict[str, Any]:
    """
    Recibe el payload del Transcriptor, lo convierte a TestimonyRequest interno
    y ejecuta el proceso.
    """
    logger.info(f"🔗 Webhook recibido para Case: {webhook_req.case_id}")
    
    meta = webhook_req.metadata
    
    # Mapeo: Webhook -> Request Interno
    internal_req = TestimonyRequest(
        case_id=webhook_req.case_id,
        context=meta.context,
        client=meta.client_name,
        witness=meta.witness_name,
        
        # La fuente es el doc que acaba de terminar el otro servicio
        transcription_doc_id=webhook_req.transcription_doc_id,
        
        # El destino y la config de sheet vienen en metadata
        output_doc_id=meta.output_doc_id,
        sheet_callback=meta.sheet_callback,
        
        language="es" # Default o lógica extra si quisieras
    )
    
    return run_testimony(internal_req)
# src/orchestration/runner.py
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from fastapi import HTTPException

from src.logging_conf import get_logger
from src.settings import get_settings
from src.domain.schemas import TestimonyRequest, TestimonyResponse
from src.clients.drive_client import assert_sa_has_access
from src.clients.gdocs_client import get_document_content, write_to_document
from src.clients.vertex_client import generate_text
from src.auth import build_drive_client
from src.domain.prompt_loader import render_testimony_prompt

logger = get_logger(__name__)
settings = get_settings()

# ---------------------------
# Utilidades
# ---------------------------

def _extract_doc_id_from_url(url: str) -> str:
    m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        raise HTTPException(
            status_code=422,
            detail="No pude extraer el doc_id del 'transcription_link'. Debes enviar un link válido de Google Docs."
        )
    return m.group(1)


def _resolve_language(req: TestimonyRequest) -> str:
    if req.language:
        return (req.language or "").lower()
    # Mantén compat con `extra.language`
    return (req.extra or {}).get("language", settings.default_language or "es").lower()


def _map_google_http_error(e: Exception, *, op: str, file_id: str) -> HTTPException:
    msg = f"{op} falló para {file_id}: {e}"
    # Normalizamos como 403 (permiso) salvo que aguas arriba lances 404 específicos
    return HTTPException(status_code=403, detail=msg)


def _fallback_prompt(transcript: str, req: TestimonyRequest, language: str) -> str:
    """
    Fallback de prompt cuando no se encuentran plantillas Jinja.
    Mantiene ES/EN con reglas Word-by-Word.
    """
    from textwrap import dedent

    if language == "es":
        system = dedent("""
        Propósito: Reescribir la transcripción en un testimonio en primera persona (español), siguiendo la regla “word by word” y sin inventar, omitir ni exagerar.
        Reglas de oro (obligatorias):
        - Entrega directamente el testimonio final. NO confirmes, NO pidas más datos, NO escribas “Entendido”, “Listo”, ni ningún mensaje meta.
        - No menciones entrevistador/psicólogo/equipo. El texto debe leerse como narrado por el testigo.
        - Mantén el vocabulario del testigo; evita tono jurídico o rebuscado.
        - Fechas y años en NÚMEROS cuando aparezcan.
        - Si hay pasajes ininteligibles, agrega al final **DUDAS PENDIENTES** con la cita literal y minuto si está presente.
        - Respeta estructura: inicio (quién soy), desarrollo (lo ocurrido con ejemplos concretos), desenlace (estado actual).
        - Protege el carácter moral del cliente; no inventes contexto.
        """).strip()

        base = dedent("""
        Reestructura TODO en primera persona manteniendo el vocabulario real del testigo.
        Inicio: datos del testigo. Desarrollo: cronología clara con ejemplos concretos.
        Cierre: coherente con lo dicho (sin hechos nuevos).
        - Voz: primera persona del testigo.
        - Idioma: español neutro, usando el léxico del testigo.
        - No incluyas encabezados técnicos del prompt en la salida.
        - No incluyas esta sección en el resultado.
        """).strip()

        meta = dedent(f"""
        [META]
        case_id: {req.case_id}
        client: {req.client or ""}
        witness: {req.witness or ""}
        context: {req.context}
        extra: {json.dumps(req.extra or {}, ensure_ascii=False)}
        idioma_salida: Español
        """).strip()

        out_fmt = dedent("""
        Datos del testigo:
           - Nombre completo:
           - Lugar de nacimiento:
           - Fecha de nacimiento:
           - Estatus migratorio (si aplica):
           - Relación con el cliente y desde cuándo:
        Testimonio (párrafos, cronología coherente).
        Inconsistencias o dudas (si aplica).
        Fragmentos no comprendidos (con minuto) — cita exacta.
        """).strip()

        return f"[SYSTEM]\n{system}\n\n{meta}\n\n[BASE]\n{base}\n\n[TRANSCRIPT]\n{transcript}\n\n[FORMATO]\n{out_fmt}"

    # EN
    system_en = (
        "Purpose: Rewrite the transcript in witness FIRST PERSON (word-by-word). "
        "No interviewer mentions. Numeric dates. Start with witness data. "
        "Append 'Unclear fragments (with minute)' and 'Inconsistencies' if needed."
    )
    base_en = (
        "Restructure EVERYTHING in first person preserving vocabulary. "
        "Start: witness data. Body: clear timeline with concrete examples. "
        "End: consistent with given facts (no new facts)."
    )
    meta_en = f"[META]\ncase_id: {req.case_id}\nclient: {req.client or ''}\nwitness: {req.witness or ''}\ncontext: {req.context}\nextra: {json.dumps(req.extra or {}, ensure_ascii=False)}\noutput_language: English"
    out_fmt_en = (
        "1) Witness data\n2) Testimony (clear paragraphs)\n3) Inconsistencies (if any)\n"
        "4) Unclear fragments (with minute) — exact quote"
    )
    return f"[SYSTEM]\n{system_en}\n\n{meta_en}\n\n[BASE]\n{base_en}\n\n[TRANSCRIPT]\n{transcript}\n\n[OUTPUT]\n{out_fmt_en}"


# ---------------------------
# Caso de uso principal
# ---------------------------

def run_testimony(req: TestimonyRequest) -> Dict[str, Any]:
    """
    Ejecuta el flujo de generación de testimonio y escribe SIEMPRE en el Doc
    indicado por `output_doc_id`. No crea documentos ni usa defaults.
    """
    logger.info(
        "🚀 run_testimony",
        extra={"case_id": req.case_id, "context": req.context, "request_id": req.request_id}
    )

    # --- 0) Validar destino: obligatorio ---
    target_doc_id = (req.output_doc_id or "").strip()
    if not target_doc_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Falta 'output_doc_id'. Este servicio NO crea documentos ni usa valores por omisión; "
                "debes enviar el ID de Google Doc de salida (compartido con la Service Account)."
            ),
        )

    # Verificar acceso de la SA al destino
    try:
        assert_sa_has_access(target_doc_id, use_docs_api=True)
    except Exception as e:
        raise _map_google_http_error(e, op="Validar acceso al documento destino (Docs)", file_id=target_doc_id)

    # --- 1) Resolver fuente ---
    language = _resolve_language(req)

    if req.raw_text:
        transcript = req.raw_text
        logger.info("Fuente: raw_text", extra={"case_id": req.case_id})
    else:
        if req.transcription_doc_id:
            src_doc = req.transcription_doc_id.strip()
            logger.info("Fuente: transcription_doc_id", extra={"case_id": req.case_id, "doc_id": src_doc})
        elif req.transcription_link:
            src_doc = _extract_doc_id_from_url(str(req.transcription_link))
            logger.info("Fuente: transcription_link→doc_id", extra={"case_id": req.case_id, "doc_id": src_doc})
        else:
            raise HTTPException(
                status_code=422,
                detail="Debes enviar 'raw_text', 'transcription_doc_id' o 'transcription_link' como fuente."
            )

        try:
            assert_sa_has_access(src_doc, use_docs_api=True)
        except Exception as e:
            raise _map_google_http_error(e, op="Validar acceso al documento fuente (Docs)", file_id=src_doc)

        try:
            transcript = get_document_content(src_doc)
        except Exception as e:
            raise _map_google_http_error(e, op="Leer contenido del documento fuente", file_id=src_doc)

    if not transcript or len(transcript.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Transcript vacío o demasiado corto para generar el testimonio (≥ 20 caracteres)."
        )

    # --- 2) Prompt + LLM ---
    try:
        prompt = render_testimony_prompt(
            language=language,
            templates_dir=settings.prompts_dir,
            transcript=transcript,
            req=req,
        )
    except Exception:
        logger.warning(
            "⚠️ Plantilla no encontrada o con error. Usando prompt fallback.",
            extra={"case_id": req.case_id, "language": language}
        )
        prompt = _fallback_prompt(transcript=transcript, req=req, language=language)

    try:
        output_text = generate_text(prompt)
    except Exception:
        logger.error("Fallo LLM", extra={"case_id": req.case_id, "request_id": req.request_id})
        raise HTTPException(status_code=500, detail="Error al generar el texto con el modelo. Intenta más tarde.")

    # --- 3) Escribir en Doc de destino (overwrite) ---
    try:
        write_to_document(target_doc_id, output_text)
    except Exception as e:
        raise _map_google_http_error(e, op="Escribir documento de salida (Docs)", file_id=target_doc_id)

    # --- 4) Obtener link web del Doc ---
    try:
        drive = build_drive_client()
        meta = drive.files().get(
            fileId=target_doc_id,
            fields="webViewLink",
            supportsAllDrives=True,
        ).execute()
        output_link = meta.get("webViewLink", f"https://docs.google.com/document/d/{target_doc_id}/edit")
    except Exception:
        output_link = f"https://docs.google.com/document/d/{target_doc_id}/edit"

    logger.info(
        "✅ Testimonio generado y escrito (doc existente)",
        extra={
            "case_id": req.case_id,
            "output_doc_id": target_doc_id,
            "lang": language,
            "model": settings.model_id,
            "request_id": req.request_id,
        },
    )

    return TestimonyResponse(
        status="success",
        message="El resultado fue escrito correctamente en el documento.",
        doc_id=target_doc_id,
        output_doc_link=output_link,
        model=settings.model_id,
        language=language,
        case_id=req.case_id,
        request_id=req.request_id,
    ).model_dump()

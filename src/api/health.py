# src/api/health.py
from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException, Query

from src.logging_conf import get_logger
from src.settings import get_settings
from src.auth import build_docs_client
from src.clients.drive_client import assert_sa_has_access

logger = get_logger(__name__)
settings = get_settings()
router = APIRouter()


@router.get("/health", summary="Ping simple")
async def health():
    return {"ok": True, "service": "testimonios", "project": settings.project_id}


@router.get("/health/sa", summary="Verificación SA/ADC de Docs (escritura reversible) y Vertex")
async def health_sa(doc_id: str | None = Query(default=None, description="Doc existente para prueba de escritura")):
    # 1) resolver doc para prueba
    test_doc = doc_id or os.getenv("HEALTHCHECK_DOC_ID")
    if not test_doc:
        raise HTTPException(status_code=422, detail="Falta doc_id en query o HEALTHCHECK_DOC_ID en el entorno.")

    # 2) acceso
    try:
        assert_sa_has_access(test_doc, use_docs_api=True)
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Sin acceso al doc {test_doc}: {e}")

    # 3) escritura reversible (insert + delete en la misma batch)
    docs = build_docs_client()
    probe = "SA health-check ✔"
    try:
        docs.documents().batchUpdate(
            documentId=test_doc,
            body={"requests": [
                {"insertText": {"location": {"index": 1}, "text": probe}},
                {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 1 + len(probe)}}},
            ]}
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"No se pudo escribir en el doc {test_doc}: {e}")

    # 4) Vertex init (sin generar, para no consumir)
    from src.clients.vertex_client import init_vertex_ai
    try:
        init_vertex_ai()
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Vertex AI no inicializó: {e}")

    return {"status": "ok", "doc_id": test_doc, "write_probe": "ok", "vertex": "ok"}
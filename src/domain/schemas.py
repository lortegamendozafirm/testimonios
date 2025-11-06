# src/domain/schemas.py
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from typing import Optional, Dict, Any, Literal


class TestimonyRequest(BaseModel):
    # Identificación y contexto
    case_id: str = Field(..., description="ID del caso (obligatorio).")
    context: str = Field(..., description="Ej: 'Witness', 'Reference Letter' (obligatorio).")
    language: Optional[Literal["es", "en"]] = Field(
        None, description="Idioma de salida. Si falta, se usa settings.default_language."
    )

    # (Opcionales, pero usados por el prompt/meta)
    client: Optional[str] = Field(None, description="Nombre del cliente (opcional).")
    witness: Optional[str] = Field(None, description="Nombre del testigo (opcional).")

    # Fuente (debe venir al menos una)
    raw_text: Optional[str] = Field(
        None, description="Texto literal de la transcripción (prioridad más alta)."
    )
    transcription_doc_id: Optional[str] = Field(
        None, description="ID de Google Doc que contiene la transcripción."
    )
    transcription_link: Optional[HttpUrl] = Field(
        None, description="Link de Google Doc; se extrae el ID automáticamente."
    )

    # ✅ Destino (obligatorio, ya no hay defaults ni creación de Docs)
    output_doc_id: str = Field(
        ...,
        description=(
            "ID del Google Doc de salida (YA compartido con la Service Account). "
            "Este servicio NO crea documentos ni usa valores por omisión."
        ),
    )

    # Extras
    extra: Optional[Dict[str, Any]] = Field(
        default=None, description="Campos libres adicionales (se pasan al prompt/meta)."
    )
    request_id: Optional[str] = Field(
        default=None, description="ID de request para trazabilidad."
    )

    # Permite llaves adicionales por compatibilidad hacia atrás
    model_config = {"extra": "allow"}

    # --- Validaciones ---

    @field_validator("output_doc_id", mode="before")
    @classmethod
    def _strip_and_require_output(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = str(v).strip()
        if not s:
            raise ValueError("output_doc_id no puede ser vacío.")
        return s

    @model_validator(mode="after")
    def _require_at_least_one_source(self):
        if not (self.raw_text or self.transcription_doc_id or self.transcription_link):
            raise ValueError(
                "Debes enviar una fuente: 'raw_text' o 'transcription_doc_id' o 'transcription_link'."
            )
        return self


class TestimonyResponse(BaseModel):
    status: str
    message: str
    doc_id: str
    output_doc_link: str
    model: str
    language: str
    case_id: str
    request_id: Optional[str] = None

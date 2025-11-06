# src/domain/prompt_loader.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from src.logging_conf import get_logger

logger = get_logger(__name__)

@lru_cache(maxsize=2)
def _get_env(templates_dir: str) -> Environment:
    # autoescape OFF para .md/.j2 (plantillas de texto)
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(disabled_extensions=("md", "j2", "jinja", "jinja2"), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,  # falla si falta una variable → mejor que silencie
    )
    return env


def render_testimony_prompt(*, language: str, templates_dir: Path,
                            transcript: str, req: Any) -> str:
    """
    Renderiza el prompt usando Jinja2.
    - Selección por idioma ('es'/'en') o por extra.template_name si viene.
    - Variables disponibles en la plantilla:
        {{ case_id }}, {{ client }}, {{ witness }}, {{ context }},
        {{ extra | tojson }}, {{ transcript }}, {{ language }}
    """
    # Permite override por request: extra.template_name
    extra = req.extra or {}
    template_from_extra = extra.get("template_name")

    name_map = {
        "es": "testimony_prompt_spanish.md.j2",
        "en": "testimony_prompt_english.md.j2",
    }
    template_name = template_from_extra or name_map.get(language, name_map["es"])

    env = _get_env(str(templates_dir))
    try:
        tmpl = env.get_template(template_name)
    except Exception as e:
        logger.error(f"No se encontró la plantilla '{template_name}' en {templates_dir}: {e}")
        raise

    ctx: Dict[str, Any] = {
        "case_id": req.case_id,
        "client": req.client,
        "witness": req.witness,
        "context": req.context,
        "extra": extra,
        "transcript": transcript,
        "language": language,
    }
    return tmpl.render(**ctx)

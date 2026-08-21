from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


def _safe_str(v: object) -> str:
    try:
        return str(v)
    except Exception:
        return repr(v)


def build_error_report(
    *,
    exc: BaseException,
    stage: str,
    pdf: str | None = None,
    extractor: object | None = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Construit un payload de rapport d'erreur sérialisable en JSON.

    Objectif : garder la console lisible tout en capturant des informations utiles au debug
    (type/message d'exception + traceback complet + contexte de configuration non sensible).
    """

    cfg = getattr(extractor, "config", None)

    # Robuste : sérialise toujours le traceback de l'exception fournie (pas "dernière exception").
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    payload: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "pdf": pdf,
        "error": {"type": exc.__class__.__name__, "message": _safe_str(exc)},
        "traceback": tb,
        "llm": {
            "base_url": getattr(cfg, "base_url", None),
            "model": getattr(cfg, "model", None),
            "api_protocol": getattr(cfg, "api_protocol", None),
            "invoke_mode": getattr(cfg, "invoke_mode", None),
        },
        "params": {
            "top_k_snippets": getattr(extractor, "top_k_snippets", None),
            "temperature": getattr(extractor, "temperature", None),
            "max_tokens": getattr(extractor, "max_tokens", None),
            "retrieval_method": getattr(extractor, "retrieval_method", None),
        },
        "env": {
            # Ne jamais inclure de secrets comme SCW_API_KEY.
            "VSM_INDICATORS_PATH": (os.getenv("VSM_INDICATORS_PATH") or "").strip()
            or None,
            "VSME_CODE_VSME_LIST": (os.getenv("VSME_CODE_VSME_LIST") or "").strip()
            or None,
            "VSME_RETRIEVAL_METHOD": (os.getenv("VSME_RETRIEVAL_METHOD") or "").strip()
            or None,
            "VSME_OUTPUT_FORMAT": (os.getenv("VSME_OUTPUT_FORMAT") or "").strip()
            or None,
        },
    }

    if extra:
        payload["extra"] = dict(extra)

    return payload


def write_error_report(report_path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Écrit le rapport d'erreur en JSON UTF‑8 et retourne le chemin."""
    p = Path(report_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return p

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal

# Coûts, éventuellement overridables par .env
EURO_COST_PER_MILLION_INPUT = float(os.getenv("VSM_INPUT_COST_EUR", 0.15))
EURO_COST_PER_MILLION_OUTPUT = float(os.getenv("VSM_OUTPUT_COST_EUR", 0.60))


def _get_env_float(name: str, default: float) -> float:
    """Parse une variable d'environnement float de façon robuste.

    Si la variable est absente/vide/invalide, retourne `default`.
    """
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    raw = raw.strip()
    if raw == "":
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


# Optionnel : seuil relatif du retrieval `count_refine`.
# Interprétation : une page est conservée si (score / best_score) >= rel_thr.
# Intervalle attendu : [0.0, 1.0]
VSME_RETRIEVAL_REL_THR = min(
    1.0, max(0.0, _get_env_float("VSME_RETRIEVAL_REL_THR", 0.60))
)

# Optionnel : seuil absolu TF‑IDF du retrieval `count_refine`.
# Interprétation : une page est conservée seulement si score >= abs_thr.
# Objectif : éviter de conserver des pages avec un score très faible (signal pauvre),
# même si elles passent le seuil relatif.
# Intervalle attendu : abs_thr >= 0.0
VSME_RETRIEVAL_ABS_THR = max(0.0, _get_env_float("VSME_RETRIEVAL_ABS_THR", 0.02))


@dataclass
class LLMConfig:
    """Configuration du client LLM (API key, endpoint, modèle, prompt système)."""

    api_key: str
    base_url: str
    model: str
    system_prompt: str = "You are a helpful assistant"
    api_protocol: Literal["chat.completions", "responses"] = "chat.completions"
    invoke_mode: Literal["invoke", "invoke_stream"] = "invoke"

    # Gestion du rate limit (HTTP 429)
    rate_limit_max_retries: int = 0
    rate_limit_retry_sleep_s: float = 60.0
    rate_limit_use_retry_after: bool = True


def load_llm_config() -> LLMConfig:
    """Charge la configuration LLM depuis les variables d'environnement.

    Variables attendues :
    - `SCW_API_KEY` (obligatoire)
    - `SCW_BASE_URL` (optionnel)
    - `SCW_MODEL_NAME` (optionnel)
    """
    api_key = os.getenv("SCW_API_KEY")
    if not api_key:
        raise RuntimeError(
            "SCW_API_KEY manquant. Définis-le dans ton environnement ou ton .env."
        )

    base_url = os.getenv(
        "SCW_BASE_URL",
        "https://api.scaleway.ai/06f1a171-1eef-4d8b-aed5-b78189d17335/v1",
    )
    model = os.getenv("SCW_MODEL_NAME", "gpt-oss-120b")

    # Permet de choisir le protocole OpenAI-compatible à utiliser selon le provider.
    # Valeurs supportées :
    # - chat.completions (compat large)
    # - responses (nouvelle API OpenAI)
    api_protocol = (
        (os.getenv("VSME_API_PROTOCOL") or "chat.completions").strip().lower()
    )
    if api_protocol not in {"chat.completions", "responses"}:
        api_protocol = "chat.completions"

    invoke_mode = (os.getenv("VSME_INVOKE_MODE") or "invoke").strip().lower()
    if invoke_mode not in {"invoke", "invoke_stream"}:
        invoke_mode = "invoke"

    # Rate limit (HTTP 429)
    try:
        rate_limit_max_retries = int(os.getenv("VSME_RATE_LIMIT_MAX_RETRIES", "0") or 0)
    except Exception:
        rate_limit_max_retries = 0
    if rate_limit_max_retries < 0:
        rate_limit_max_retries = 0

    try:
        rate_limit_retry_sleep_s = float(
            os.getenv("VSME_RATE_LIMIT_RETRY_SLEEP_S", "60") or 60
        )
    except Exception:
        rate_limit_retry_sleep_s = 60.0
    if rate_limit_retry_sleep_s < 0:
        rate_limit_retry_sleep_s = 0.0

    rate_limit_use_retry_after = os.getenv(
        "VSME_RATE_LIMIT_USE_RETRY_AFTER", "1"
    ).strip().lower() in {"1", "true", "yes", "y", "on"}

    return LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        api_protocol=api_protocol,  # type: ignore[arg-type]
        invoke_mode=invoke_mode,  # type: ignore[arg-type]
        rate_limit_max_retries=rate_limit_max_retries,
        rate_limit_retry_sleep_s=rate_limit_retry_sleep_s,
        rate_limit_use_retry_after=rate_limit_use_retry_after,
    )

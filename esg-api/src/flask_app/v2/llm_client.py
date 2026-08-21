from __future__ import annotations

from collections.abc import Mapping
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional, Dict, TypedDict, Callable, TypeVar

from openai import OpenAI
from tiktoken import get_encoding

from .config import (
    LLMConfig,
    EURO_COST_PER_MILLION_INPUT,
    EURO_COST_PER_MILLION_OUTPUT,
)
from .logging_utils import SizedTimedRotatingFileHandler


logger = logging.getLogger(__name__)


class LLMCostEUR(TypedDict):
    input: float
    output: float
    total: float


class LLMResponse(TypedDict):
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_eur: LLMCostEUR
    used_api_usage: bool


PROMPTS_LOGGER = logging.getLogger("vsme_extractor.prompts")
_PROMPTS_LOGGER_CONFIGURED = False


def _env_bool(name: str) -> bool:
    """
    Parse une variable d’environnement booléenne : 1/0, true/false, yes/no, on/off.

    Par défaut : False si la variable n’existe pas ou si la valeur est non reconnue.
    """
    v = os.getenv(name)
    if v is None:
        return False
    s = v.strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _format_prompt_block(
    *,
    model: str,
    base_url: str,
    system: str,
    context: str | None,
    user: str,
) -> str:
    """Formate un bloc de prompt (system+context+user) pour audit/logging."""
    # Sépare clairement les blocs pour faciliter la relecture/audit
    context_block = ""
    if context is not None and str(context).strip() != "":
        context_block = f"------------------- CONTEXT -------------------\n{context}\n"
    return (
        "\n"
        "==================== LLM PROMPT (BEGIN) ====================\n"
        f"model: {model}\n"
        f"base_url: {base_url}\n"
        "-------------------- SYSTEM --------------------\n"
        f"{system}\n"
        f"{context_block}"
        "--------------------- USER ---------------------\n"
        f"{user}\n"
        "===================== LLM PROMPT (END) =====================\n"
    )


def _configure_prompts_logger() -> bool:
    """
    Configure les sorties de logging des prompts (séparées du logger applicatif global).

    Variables d’environnement :
      - VSME_PROMPT_FILE : chemin vers un fichier de trace des prompts (optionnel)
      - VSME_PROMPT_STDOUT : 1/0, true/false, yes/no, on/off

    Comportement :
      - Si aucune destination n’est activée, le logging des prompts est désactivé.
      - Les prompts ne propagent jamais vers le root logger (ils n’apparaissent donc PAS dans VSME_LOG_FILE).
      - Si un fichier est configuré, il est soumis à la même rotation que les logs applicatifs :
        rotation quotidienne + rotation à ~10 Mo, avec rétention 7 jours.
    """
    global _PROMPTS_LOGGER_CONFIGURED

    prompt_file = (os.getenv("VSME_PROMPT_FILE") or "").strip() or None
    prompt_stdout = _env_bool("VSME_PROMPT_STDOUT")

    enabled = bool(prompt_file) or prompt_stdout
    if not enabled:
        return False

    if _PROMPTS_LOGGER_CONFIGURED:
        return True

    PROMPTS_LOGGER.setLevel(logging.INFO)
    PROMPTS_LOGGER.propagate = (
        False  # critique : ne doit pas "fuiter" vers les handlers du root
    )

    # Garantit l'idempotence si appelé plusieurs fois
    for h in list(PROMPTS_LOGGER.handlers):
        PROMPTS_LOGGER.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    if prompt_stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        PROMPTS_LOGGER.addHandler(sh)

    if prompt_file:
        path = Path(prompt_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        fh = SizedTimedRotatingFileHandler(
            path,
            when="midnight",
            interval=1,
            utc=False,
            max_bytes=10_000_000,  # < 10 Mo
            retention_days=7,
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        PROMPTS_LOGGER.addHandler(fh)

    _PROMPTS_LOGGER_CONFIGURED = True
    return True


def _safe_log_prompt(
    *, model: str, base_url: str, system: str, context: str | None, user: str
) -> None:
    """Loggue le prompt si (et seulement si) la config d'audit des prompts est activée."""
    if not _configure_prompts_logger():
        return
    PROMPTS_LOGGER.info(
        "%s",
        _format_prompt_block(
            model=model,
            base_url=base_url,
            system=system,
            context=context,
            user=user,
        ),
    )


def _safe_get_usage(resp: Any) -> Optional[Dict[str, int]]:
    """Récupère les compteurs de tokens depuis une réponse provider (au mieux)."""
    usage = getattr(resp, "usage", None)
    if usage is not None:
        if hasattr(usage, "prompt_tokens"):
            return dict(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            )
        # Responses API (OpenAI) : input_tokens / output_tokens
        if hasattr(usage, "input_tokens"):
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            total_tokens = int(
                getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
            )
            return dict(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        if isinstance(usage, Mapping):
            if "prompt_tokens" in usage or "completion_tokens" in usage:
                return dict(
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or 0),
                )
            if "input_tokens" in usage or "output_tokens" in usage:
                prompt_tokens = int(usage.get("input_tokens") or 0)
                completion_tokens = int(usage.get("output_tokens") or 0)
                total_tokens = int(
                    usage.get("total_tokens") or (prompt_tokens + completion_tokens)
                )
                return dict(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
    try:
        data = resp.model_dump()
        if "usage" in data:
            u = data["usage"]
            if "prompt_tokens" in u or "completion_tokens" in u:
                return dict(
                    prompt_tokens=int(u.get("prompt_tokens") or 0),
                    completion_tokens=int(u.get("completion_tokens") or 0),
                    total_tokens=int(u.get("total_tokens") or 0),
                )
            if "input_tokens" in u or "output_tokens" in u:
                prompt_tokens = int(u.get("input_tokens") or 0)
                completion_tokens = int(u.get("output_tokens") or 0)
                total_tokens = int(
                    u.get("total_tokens") or (prompt_tokens + completion_tokens)
                )
                return dict(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
    except Exception:
        pass
    return None


def _estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens pour un texte (tiktoken si dispo, sinon heuristique)."""
    try:
        enc = get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, int(round(len(text) / 4)))


def _usage_from_obj(u):
    """Normalise un objet/dict 'usage' vers un dict standard."""
    if not u:
        return None
    if hasattr(u, "prompt_tokens"):
        return {
            "prompt_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(u, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
        }
    if isinstance(u, dict):
        return {
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
        }
    return None


class LLM:
    """Client LLM OpenAI-compatible avec estimation de tokens et coût."""

    def __init__(self, config: LLMConfig):
        """Initialise le client OpenAI-compatible avec la config fournie."""
        self.config = config
        self.client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    def _is_rate_limit_error(self, e: Exception) -> bool:
        """Détecte (au mieux) une erreur de rate limit (HTTP 429) depuis une exception OpenAI-compatible."""
        try:
            # openai>=1.x
            from openai import RateLimitError  # type: ignore

            if isinstance(e, RateLimitError):
                return True
        except Exception:
            pass

        status = getattr(e, "status_code", None)
        if status == 429:
            return True

        # Fallback best-effort : certains wrappers exposent `response.status_code`
        resp = getattr(e, "response", None)
        try:
            if resp is not None and getattr(resp, "status_code", None) == 429:
                return True
        except Exception:
            pass

        return False

    def _get_retry_after_s(self, e: Exception) -> float | None:
        """Récupère un délai de retry depuis les headers (Retry-After), si disponible."""
        resp = getattr(e, "response", None)
        if resp is None:
            return None
        headers = getattr(resp, "headers", None)
        if not headers:
            return None
        # httpx headers sont case-insensitive
        ra = None
        try:
            ra = headers.get("retry-after") or headers.get("Retry-After")
        except Exception:
            ra = None
        if not ra:
            return None
        try:
            return float(str(ra).strip())
        except Exception:
            return None

    _T = TypeVar("_T")

    def _call_with_rate_limit_retry(self, fn: Callable[[], _T], *, action: str) -> _T:
        """Exécute `fn()` avec retry sur 429 (RateLimitError), selon la configuration.

        Implémentation via tenacity pour une gestion robuste (stop/wait/logging).
        """
        max_retries = int(getattr(self.config, "rate_limit_max_retries", 0) or 0)
        sleep_s = float(getattr(self.config, "rate_limit_retry_sleep_s", 60.0) or 60.0)
        use_retry_after = bool(getattr(self.config, "rate_limit_use_retry_after", True))

        # 0 retry => appel direct.
        if max_retries <= 0:
            return fn()

        from tenacity import Retrying, retry_if_exception, stop_after_attempt

        def _wait(retry_state) -> float:
            # Valeur fixe configurée, avec possibilité d'augmenter via Retry-After.
            wait_s = sleep_s
            if use_retry_after:
                try:
                    e = retry_state.outcome.exception()
                    ra = self._get_retry_after_s(e) if e is not None else None
                    if ra is not None:
                        wait_s = max(wait_s, ra)
                except Exception:
                    pass
            return max(0.0, float(wait_s))

        def _before_sleep(retry_state) -> None:
            # attempt_number démarre à 1. Le nombre total de tentatives = max_retries + 1.
            try:
                sleep_next = float(
                    getattr(getattr(retry_state, "next_action", None), "sleep", 0.0)
                    or 0.0
                )
            except Exception:
                sleep_next = 0.0
            logger.warning(
                "Rate limit (429) | action=%s | attempt=%s/%s | sleeping_s=%.1f",
                action,
                int(getattr(retry_state, "attempt_number", 0) or 0),
                max_retries + 1,
                sleep_next,
            )

        retrying = Retrying(
            retry=retry_if_exception(self._is_rate_limit_error),
            stop=stop_after_attempt(max_retries + 1),
            wait=_wait,
            before_sleep=_before_sleep,
            reraise=True,
        )

        for attempt in retrying:
            with attempt:
                return fn()

        # Sécurité : le retrying ci-dessus doit toujours exécuter au moins une tentative.
        raise RuntimeError("Tenacity retry loop did not execute")

    def _chat_completions_create(self, **kwargs: Any) -> Any:
        return self._call_with_rate_limit_retry(
            lambda: self.client.chat.completions.create(**kwargs),
            action="chat.completions.create",
        )

    def _responses_create(self, **kwargs: Any) -> Any:
        return self._call_with_rate_limit_retry(
            lambda: self.client.responses.create(**kwargs),
            action="responses.create",
        )

    def invoke(
        self,
        question: str,
        temperature: float = 0.0,  # extraction -> déterministe par défaut
        max_tokens: int = 1024,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
    ) -> LLMResponse:
        """Appel LLM avec priorité à Responses API (quand dispo pour gpt-oss-120b),
        sans JSON-mode serveur (non supporté sur ton endpoint), puis fallback chat.completions.
        Ajoute un fallback de parsing si content est vide (reasoning/reasoning_content).
        """

        import json

        def _extract_first_json_object(s: str) -> str:
            """Extrait le premier objet JSON {...} d'une chaîne, au mieux."""
            s = (s or "").strip()
            if not s:
                return s
            start = s.find("{")
            end = s.rfind("}")
            if start != -1 and end != -1 and end > start:
                return s[start : end + 1]
            return s

        def _is_valid_json_object(s: str) -> bool:
            try:
                obj = json.loads(_extract_first_json_object(s))
                return isinstance(obj, dict)
            except Exception:
                return False

        system = system_prompt or self.config.system_prompt

        # Permet de choisir dynamiquement le mode d'appel via env (VSME_INVOKE_MODE)
        # sans changer les call-sites. On n'active ce chemin que pour chat.completions,
        # sinon on risquerait une boucle invoke -> invoke_stream -> invoke.
        if (
            getattr(self.config, "invoke_mode", "invoke") == "invoke_stream"
            and self.config.api_protocol == "chat.completions"
        ):
            return self.invoke_stream(
                question=question,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                context=context,
                print_tokens=False,
            )

        _safe_log_prompt(
            model=self.config.model,
            base_url=self.config.base_url,
            system=system,
            context=context,
            user=question,
        )

        # Messages compatibles à la fois pour responses et chat.completions
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if context is not None and str(context).strip() != "":
            messages.append(
                {"role": "user", "content": f"CONTEXT:\n{context}\n\n[END CONTEXT]"}
            )
        messages.append({"role": "user", "content": question})

        text = ""
        usage = None
        used_api_usage = False

        # -------- 1) Protocole configuré via env : VSME_API_PROTOCOL
        if self.config.api_protocol == "responses":
            # Tentative Responses API (sans json_object: non supporté sur certains endpoints)
            try:
                resp = self._responses_create(
                    model=self.config.model,
                    input=messages,
                    reasoning={"effort": "low"},
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    text={"format": {"type": "text"}},  # IMPORTANT: pas "json_object"
                )

                # Récupère le texte via output_text (souvent plus stable)
                text = getattr(resp, "output_text", "") or ""
                if not text:
                    try:
                        data = resp.model_dump()
                        text = data.get("output_text") or ""
                    except Exception:
                        text = ""

                # Usage Responses (si dispo)
                usage = _safe_get_usage(resp)
                used_api_usage = usage is not None

            except Exception as e:
                # Responses non supporté / erreur endpoint -> fallback chat.completions
                logger.info(
                    "Responses API not available, fallback to chat.completions | err=%s",
                    repr(e),
                )
                resp = self._chat_completions_create(
                    model=self.config.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=1,
                    presence_penalty=0,
                    stream=False,
                    response_format={"type": "text"},  # IMPORTANT: pas "json_object"
                    extra_body={
                        "reasoning": {"effort": "low"}
                    },  # approximation (au mieux)
                )

                choice0 = resp.choices[0]
                msg_obj = getattr(choice0, "message", None)

                msg_dump = None
                # 1) content standard
                if isinstance(msg_obj, Mapping):
                    text = msg_obj.get("content") or msg_obj.get("text") or ""
                    msg_dump = msg_obj
                else:
                    text = getattr(msg_obj, "content", "") or ""
                    try:
                        msg_dump = (
                            msg_obj.model_dump()
                            if msg_obj is not None and hasattr(msg_obj, "model_dump")
                            else None
                        )
                    except Exception:
                        msg_dump = None

                # 2) fallback: certains proxys mettent la génération dans reasoning(_content)
                if not (text or "").strip() and isinstance(msg_dump, dict):
                    text = (
                        msg_dump.get("reasoning_content")
                        or msg_dump.get("reasoning")
                        or msg_dump.get("content")
                        or msg_dump.get("text")
                        or ""
                    )

                # 3) dernier fallback: dump complet
                if not (text or "").strip():
                    try:
                        data = resp.model_dump()
                        m = data["choices"][0]["message"]
                        text = (
                            m.get("content")
                            or m.get("text")
                            or m.get("reasoning_content")
                            or m.get("reasoning")
                            or ""
                        )
                    except Exception:
                        text = ""

                # Warning si toujours vide
                if not (text or "").strip():
                    finish_reason = getattr(choice0, "finish_reason", None)
                    logger.warning(
                        "LLM empty response text | model=%s | base_url=%s | finish_reason=%s | message=%s",
                        self.config.model,
                        self.config.base_url,
                        finish_reason,
                        msg_dump,
                    )

                usage = _safe_get_usage(resp)
                used_api_usage = usage is not None

        else:
            # Protocole chat.completions (par défaut)
            resp = self._chat_completions_create(
                model=self.config.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=1,
                presence_penalty=0,
                stream=False,
                response_format={"type": "text"},  # IMPORTANT: pas "json_object"
                extra_body={"reasoning": {"effort": "low"}},  # approximation (au mieux)
            )

            choice0 = resp.choices[0]
            msg_obj = getattr(choice0, "message", None)

            msg_dump = None
            # 1) content standard
            if isinstance(msg_obj, Mapping):
                text = msg_obj.get("content") or msg_obj.get("text") or ""
                msg_dump = msg_obj
            else:
                text = getattr(msg_obj, "content", "") or ""
                try:
                    msg_dump = (
                        msg_obj.model_dump()
                        if msg_obj is not None and hasattr(msg_obj, "model_dump")
                        else None
                    )
                except Exception:
                    msg_dump = None

            # 2) fallback: certains proxys mettent la génération dans reasoning(_content)
            if not (text or "").strip() and isinstance(msg_dump, dict):
                text = (
                    msg_dump.get("reasoning_content")
                    or msg_dump.get("reasoning")
                    or msg_dump.get("content")
                    or msg_dump.get("text")
                    or ""
                )

            # 3) dernier fallback: dump complet
            if not (text or "").strip():
                try:
                    data = resp.model_dump()
                    m = data["choices"][0]["message"]
                    text = (
                        m.get("content")
                        or m.get("text")
                        or m.get("reasoning_content")
                        or m.get("reasoning")
                        or ""
                    )
                except Exception:
                    text = ""

            # Warning si toujours vide
            if not (text or "").strip():
                finish_reason = getattr(choice0, "finish_reason", None)
                logger.warning(
                    "LLM empty response text | model=%s | base_url=%s | finish_reason=%s | message=%s",
                    self.config.model,
                    self.config.base_url,
                    finish_reason,
                    msg_dump,
                )

            usage = _safe_get_usage(resp)
            used_api_usage = usage is not None

        # -------- 2) Optionnel mais conseillé : validation JSON + retry court si invalide/vide
        # (désactivable si un retry automatique n'est pas souhaité)
        if self.config.api_protocol == "chat.completions" and (
            not (text or "").strip() or not _is_valid_json_object(text)
        ):
            # Retry "court" : on réduit le risque de verbosité
            # -> température 0, max_tokens plus petit, et on demande une sortie JSON ultra courte.
            retry_question = (
                question
                + "\n\nIMPORTANT: Réponds en une seule ligne JSON valide, sans aucune explication."
            )
            try:
                resp2 = self._chat_completions_create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system},
                        *(
                            [
                                {
                                    "role": "user",
                                    "content": f"CONTEXT:\n{context}\n\n[END CONTEXT]",
                                }
                            ]
                            if context
                            else []
                        ),
                        {"role": "user", "content": retry_question},
                    ],
                    max_tokens=min(max_tokens, 512),
                    temperature=0.0,
                    top_p=1,
                    presence_penalty=0,
                    stream=False,
                    response_format={"type": "text"},
                    extra_body={"reasoning": {"effort": "low"}},
                )
                c0 = resp2.choices[0]
                m2 = getattr(c0, "message", None)
                if isinstance(m2, Mapping):
                    t2 = m2.get("content") or m2.get("text") or ""
                    md2 = m2
                else:
                    t2 = getattr(m2, "content", "") or ""
                    try:
                        md2 = (
                            m2.model_dump()
                            if m2 is not None and hasattr(m2, "model_dump")
                            else None
                        )
                    except Exception:
                        md2 = None

                if (not (t2 or "").strip()) and isinstance(md2, dict):
                    t2 = md2.get("reasoning_content") or md2.get("reasoning") or ""

                if (t2 or "").strip() and _is_valid_json_object(t2):
                    text = t2  # on remplace par le retry si mieux
                    # usage retry si dispo (sinon on garde le précédent)
                    u2 = _safe_get_usage(resp2)
                    if u2:
                        usage = u2
                        used_api_usage = True
            except Exception:
                pass

        # -------- 3) Tokens/costs (usage exact si dispo sinon estimation)
        if usage:
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(
                usage.get("total_tokens") or (prompt_tokens + completion_tokens)
            )
        else:
            prompt_tokens = _estimate_tokens(
                f"{system}\n{context or ''}\n{question}".strip()
            )
            completion_tokens = _estimate_tokens(text)
            total_tokens = prompt_tokens + completion_tokens
            used_api_usage = False

        cost_prompt_eur = (prompt_tokens / 1_000_000) * EURO_COST_PER_MILLION_INPUT
        cost_completion_eur = (
            completion_tokens / 1_000_000
        ) * EURO_COST_PER_MILLION_OUTPUT

        # -------- 4) Normalisation finale (optionnel): on renvoie le JSON "nettoyé"
        # (Si la réponse brute doit être conservée, commenter les 3 lignes ci-dessous.)
        try:
            text = json.dumps(
                json.loads(_extract_first_json_object(text)), ensure_ascii=False
            )
        except Exception:
            # on laisse text tel quel
            pass

        return {
            "text": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_eur": {
                "input": cost_prompt_eur,
                "output": cost_completion_eur,
                "total": cost_prompt_eur + cost_completion_eur,
            },
            "used_api_usage": used_api_usage,
        }

    # Variante streaming : écrit les tokens au fil de l'eau (optionnel) et retourne les métriques d'usage
    def invoke_stream(
        self,
        question: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        print_tokens=True,
    ) -> LLMResponse:
        """
        Stream la réponse sur stdout au fur et à mesure et retourne :

        {
          text,
          prompt_tokens, completion_tokens, total_tokens,
          cost_eur: {input, output, total},
          used_api_usage (bool),
          finish_reason
        }
        """
        # Sortie accumulée. Certains proxys OpenAI-compatibles renvoient à tort le texte
        # complet « accumulé jusqu'ici » dans chaque chunk, au lieu de vrais deltas.
        # On corrige ça en transformant ces chunks « accumulés » en delta (suffixe).
        assembled = ""
        usage_final = None
        finish_reason = None

        import json

        def _extract_first_json_object(s: str) -> str:
            s = (s or "").strip()
            if not s:
                return s
            start = s.find("{")
            end = s.rfind("}")
            if start != -1 and end != -1 and end > start:
                return s[start : end + 1]
            return s

        def _is_valid_json_object(s: str) -> bool:
            try:
                obj = json.loads(_extract_first_json_object(s))
                return isinstance(obj, dict)
            except Exception:
                return False

        # Aligne les paramètres avec `invoke()` : effort bas pour réduire les sorties verboses.
        extra_body = {"reasoning": {"effort": "low"}}  # ou "low"/"medium"/"high"
        system = system_prompt or self.config.system_prompt

        _safe_log_prompt(
            model=self.config.model,
            base_url=self.config.base_url,
            system=system,
            context=context,
            user=question,
        )

        # Messages alignés avec invoke()
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if context is not None and str(context).strip() != "":
            messages.append(
                {"role": "user", "content": f"CONTEXT:\n{context}\n\n[END CONTEXT]"}
            )
        messages.append({"role": "user", "content": question})

        # Si le provider est configuré en Responses API, on ne stream pas ici : fallback sur invoke().
        if self.config.api_protocol == "responses":
            resp = self.invoke(
                question=question,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                context=context,
            )
            if print_tokens:
                sys.stdout.write(resp["text"] + "\n")
                sys.stdout.flush()
            return resp

        stream = self._chat_completions_create(
            model=self.config.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=1,
            presence_penalty=0,
            stream=True,
            stream_options={
                "include_usage": True
            },  # si supporté, ajoute un dernier chunk contenant l'usage
            response_format={"type": "text"},
            extra_body=extra_body,  # spécifique au provider
        )

        for chunk in stream:
            # 1) Tokens texte
            try:
                choice = chunk.choices[0]
            except Exception:
                choice = None

            if choice is not None:
                delta = getattr(choice, "delta", None)
                token = getattr(delta, "content", None) if delta is not None else None

                # Certains proxies renvoient des dicts
                if token is None and isinstance(delta, dict):
                    token = delta.get("content")

                if token:
                    # Convertit les chunks potentiellement « accumulés » en delta.
                    # - Comportement OpenAI normal : `token` est un delta -> ne commence pas par `assembled`.
                    # - Comportement proxy buggé : `token` == texte complet jusqu'ici -> commence par `assembled`.
                    if token.startswith(assembled):
                        delta_text = token[len(assembled) :]
                    elif assembled and assembled.endswith(token):
                        # Doublon pur (rare) : on ignore.
                        delta_text = ""
                    else:
                        delta_text = token

                    if delta_text:
                        if print_tokens:
                            sys.stdout.write(delta_text)
                            sys.stdout.flush()
                        assembled += delta_text

                # récupère finish_reason lorsqu'il apparaît (souvent dans le dernier chunk)
                fr = getattr(choice, "finish_reason", None)
                if fr is None and isinstance(choice, dict):
                    fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr

            # 2) Usage (si le proxy l'émet dans un chunk final)
            u = getattr(chunk, "usage", None)
            if u is None and isinstance(chunk, dict):
                u = chunk.get("usage")
            u_norm = _usage_from_obj(u)
            if u_norm:
                usage_final = u_norm

        if print_tokens:
            sys.stdout.write("\n")
            sys.stdout.flush()

        text = assembled
        chars_out = len(text)

        if not (text or "").strip():
            logger.warning(
                "LLM empty response text (stream) | model=%s | base_url=%s | finish_reason=%s",
                self.config.model,
                self.config.base_url,
                finish_reason,
            )

        # Calcule les tokens (préfère l'usage exact si disponible)
        if usage_final:
            prompt_tokens = int(usage_final["prompt_tokens"] or 0)
            completion_tokens = int(usage_final["completion_tokens"] or 0)
            total_tokens = int(
                usage_final.get("total_tokens", prompt_tokens + completion_tokens)
            )

            used_api_usage = True

        else:
            prompt_tokens = _estimate_tokens(
                f"{system}\n{context or ''}\n{question}".strip()
            )
            completion_tokens = _estimate_tokens(text)
            total_tokens = prompt_tokens + completion_tokens
            used_api_usage = False

        # Sanity check : certains providers/proxies renvoient des compteurs d'usage incohérents
        # en streaming (ex. valeurs en caractères, ou agrégation incorrecte).
        est_prompt = _estimate_tokens(f"{system}\n{context or ''}\n{question}".strip())
        if used_api_usage and est_prompt > 0:
            # Si le provider annonce un prompt_tokens largement supérieur à l'estimation,
            # on repasse en mode estimation pour éviter de fausser les stats/coûts.
            if prompt_tokens > max(est_prompt * 5, est_prompt + 5000):
                logger.warning(
                    "Suspicious usage from provider (stream) | model=%s | base_url=%s | prompt_tokens=%s | est_prompt=%s | overriding_to_estimate",
                    self.config.model,
                    self.config.base_url,
                    prompt_tokens,
                    est_prompt,
                )
                # Si l'usage prompt est fantaisiste, l'usage completion l'est souvent aussi (0, énorme, etc.).
                # On bascule donc prompt+completion vers des estimations locales basées sur le texte réel.
                prompt_tokens = est_prompt
                completion_tokens = _estimate_tokens(text)
                total_tokens = prompt_tokens + completion_tokens
                used_api_usage = False

        est_comp = _estimate_tokens(text)
        if used_api_usage and est_comp > 0:
            if (
                completion_tokens > max(est_comp * 5, est_comp + 2000)
                and completion_tokens > 2000
            ):
                logger.warning(
                    "Suspicious usage from provider (stream) | model=%s | base_url=%s | completion_tokens=%s | est_completion=%s | overriding_to_estimate",
                    self.config.model,
                    self.config.base_url,
                    completion_tokens,
                    est_comp,
                )
                completion_tokens = est_comp
                total_tokens = prompt_tokens + completion_tokens
                used_api_usage = False

        # Trace légère pour vérifier la volumétrie réelle (sans logguer le contenu).
        # On loggue uniquement si la sortie est volumineuse ou si l'usage provider est utilisé.
        if completion_tokens > 1000 or est_comp > 1000 or used_api_usage:
            logger.debug(
                "invoke_stream output stats | model=%s | base_url=%s | chars_out=%s | est_completion_tokens=%s | completion_tokens=%s | used_api_usage=%s | finish_reason=%s",
                self.config.model,
                self.config.base_url,
                chars_out,
                est_comp,
                completion_tokens,
                used_api_usage,
                finish_reason,
            )

        # Calcul des coûts
        cost_prompt_eur = (prompt_tokens / 1_000_000) * EURO_COST_PER_MILLION_INPUT
        cost_completion_eur = (
            completion_tokens / 1_000_000
        ) * EURO_COST_PER_MILLION_OUTPUT

        # Optionnel : post-validation + retry (uniquement si on ne print pas les tokens, sinon double affichage)
        # On déclenche aussi un retry si la sortie est "trop longue" (JSON valide mais verbeux),
        # afin d'aligner les coûts/volumétrie avec `invoke()`.
        too_long = _estimate_tokens(text) > 800
        if (not print_tokens) and (
            not (text or "").strip() or not _is_valid_json_object(text) or too_long
        ):
            retry_question = (
                question
                + "\n\nIMPORTANT: Réponds en une seule ligne JSON valide, sans aucune explication. "
                + "Le champ 'paragraphe' doit être un extrait court (<= 250 caractères)."
            )
            try:
                resp2 = self._chat_completions_create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system},
                        *(
                            [
                                {
                                    "role": "user",
                                    "content": f"CONTEXT:\n{context}\n\n[END CONTEXT]",
                                }
                            ]
                            if context
                            else []
                        ),
                        {"role": "user", "content": retry_question},
                    ],
                    max_tokens=min(max_tokens, 512),
                    temperature=0.0,
                    top_p=1,
                    presence_penalty=0,
                    stream=False,
                    response_format={"type": "text"},
                    extra_body={"reasoning": {"effort": "low"}},
                )
                c0 = resp2.choices[0]
                m2 = getattr(c0, "message", None)
                if isinstance(m2, Mapping):
                    t2 = m2.get("content") or m2.get("text") or ""
                else:
                    t2 = getattr(m2, "content", "") or ""
                if (t2 or "").strip() and _is_valid_json_object(t2):
                    text = t2
            except Exception:
                pass

        # Normalisation finale (comme invoke())
        try:
            text = json.dumps(
                json.loads(_extract_first_json_object(text)), ensure_ascii=False
            )
        except Exception:
            pass

        return {
            "text": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_eur": {
                "input": cost_prompt_eur,
                "output": cost_completion_eur,
                "total": cost_prompt_eur + cost_completion_eur,
            },
            "used_api_usage": used_api_usage,
        }

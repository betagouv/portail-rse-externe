from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import time
from typing import Dict, Literal, Tuple

import pandas as pd
from langdetect import LangDetectException, detect
from langdetect.detector_factory import DetectorFactory


from .config import (
    EURO_COST_PER_MILLION_INPUT,
    EURO_COST_PER_MILLION_OUTPUT,
    load_llm_config,
)
from .extraction import extract_value_for_metric
from .indicators import get_indicators
from .llm_client import LLM
from .pdf_loader import load_pdf
from .retrieval import find_relevant_snippets_with_details


logger = logging.getLogger(__name__)


@dataclass
class ExtractionStats:
    """Statistiques d'exécution (tokens et coût estimé)."""

    total_indicators: int
    indicators_llm_queried: int
    indicators_value_found: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_eur: float


# Garantit que langdetect est déterministe d'une exécution à l'autre
DetectorFactory.seed = 0


def detect_document_language(page_texts: list[str]) -> str:
    """
    Détecte la langue principale du document à partir des premières pages.

    Retourne :
        - 'fr' pour français,
        - 'en' pour anglais,
        - ou un code ISO à 2 lettres renvoyé par langdetect.

    Note:
        Si le texte extrait est vide / trop court (ex: PDF scanné sans OCR) ou si la
        détection échoue, on retourne par défaut `'en'`.
    """
    # Concatène les premières pages pour obtenir un échantillon représentatif
    sample = " ".join(page_texts[:5])  # ~5 pages suffisent généralement
    sample = sample.strip()

    if len(sample) < 50:
        # Pas assez de texte : par défaut on considère "en"
        return "en"

    try:
        lang = detect(sample)
        return lang  # ex. 'fr', 'en', 'de', ...
    except LangDetectException:
        # Détection impossible : par défaut on considère "en"
        return "en"


class VSMExtractor:
    """Pipeline principal d'extraction VSME depuis un PDF.

    Étapes : chargement PDF -> sélection d'extraits -> extraction LLM -> agrégation en DataFrame.
    """

    def __init__(
        self,
        top_k_snippets: int = 6,
        temperature: float = 0.2,
        max_tokens: int = 512,
        retrieval_method: Literal[
            "count",
            "count_refine",
        ] = "count",
    ):
        """Initialise l'extracteur (LLM + paramètres de retrieval/extraction)."""
        self.config = load_llm_config()
        self.llm = LLM(self.config)

        # Audit : petit “healthcheck” pour tracer dans les logs que le LLM répond.
        # On garde ça minimal pour limiter coût/latence (requiert tout de même un accès réseau).
        #
        # Important : certains providers peuvent être temporairement indisponibles.
        # Variables d'env :
        #   - VSME_LLM_HEALTHCHECK=0/false pour désactiver totalement
        #   - VSME_LLM_HEALTHCHECK_STRICT=0/false pour ne PAS faire échouer le démarrage si le check échoue
        hc_enabled = (os.getenv("VSME_LLM_HEALTHCHECK") or "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
        hc_strict = (
            os.getenv("VSME_LLM_HEALTHCHECK_STRICT") or "1"
        ).strip().lower() in {"1", "true", "yes", "y", "on"}

        if not hc_enabled:
            logger.info(
                "LLM healthcheck disabled | model=%s | base_url=%s",
                self.config.model,
                self.config.base_url,
            )
        else:
            try:
                health = self.llm.invoke(
                    question="Réponds uniquement: OK",
                    temperature=0.0,
                    max_tokens=4,
                    system_prompt="Réponds uniquement: OK",
                )
                ok_text = (health.get("text", "") or "").strip()
                logger.info(
                    "LLM opérationnel | model=%s | base_url=%s | api_protocol=%s | invoke_mode=%s | response=%s",
                    self.config.model,
                    self.config.base_url,
                    getattr(self.config, "api_protocol", "chat.completions"),
                    getattr(self.config, "invoke_mode", "invoke"),
                    ok_text,
                )
            except Exception:
                # Par défaut, on évite d'imprimer un traceback dans la sortie standard.
                # (Le traceback reste accessible via des mécanismes dédiés côté CLI/app : rapport JSON d'erreur,
                # ou via VSME_LOG_TRACEBACK=1 si besoin.)
                log_tb = (os.getenv("VSME_LOG_TRACEBACK") or "0").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                    "on",
                }
                if log_tb:
                    logger.error(
                        "LLM check failed | model=%s | base_url=%s | strict=%s",
                        self.config.model,
                        self.config.base_url,
                        hc_strict,
                        exc_info=True,
                    )
                else:
                    logger.error(
                        "LLM check failed | model=%s | base_url=%s | strict=%s (enable traceback with VSME_LOG_TRACEBACK=1)",
                        self.config.model,
                        self.config.base_url,
                        hc_strict,
                    )
                if hc_strict:
                    raise

        self.top_k_snippets = top_k_snippets
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retrieval_method: Literal[
            "count",
            "count_refine",
        ] = retrieval_method

        # Cache de traduction des mots-clés : (lang, keywords) -> translated_keywords
        self._keywords_translation_cache: Dict[tuple[str, str], str] = {}

    def extract_from_pdf(self, pdf_path: str) -> Tuple[pd.DataFrame, ExtractionStats]:
        """Extrait les indicateurs d'un PDF et retourne (DataFrame, stats)."""
        t_total0 = time.perf_counter()
        logger.info(
            "START extract_from_pdf | pdf_path=%s | retrieval_method=%s",
            pdf_path,
            self.retrieval_method,
        )

        t0 = time.perf_counter()
        pages, page_texts, full_text = load_pdf(pdf_path)
        t_load_pdf = time.perf_counter() - t0
        logger.info(
            "Step load_pdf | duration_s=%.3f | pages=%s | chars_full_text=%s",
            t_load_pdf,
            len(pages),
            len(full_text),
        )

        # Charge la liste des indicateurs à chercher
        t0 = time.perf_counter()
        indicateurs = get_indicators()
        t_indicators = time.perf_counter() - t0
        logger.info(
            "Step get_indicators | duration_s=%.3f | count=%s",
            t_indicators,
            len(indicateurs),
        )

        # Détecte la langue du document
        t0 = time.perf_counter()
        lang = detect_document_language(page_texts)
        t_lang = time.perf_counter() - t0
        logger.info("Step detect_language | duration_s=%.3f | lang=%s", t_lang, lang)

        if lang == "fr":
            keywords_tag = "Mots clés"
        else:
            keywords_tag = "Keywords"

        results = []
        tot_in_tokens = 0
        tot_out_tokens = 0
        llm_queried = 0
        value_found = 0

        t0 = time.perf_counter()
        # Boucle sur chaque indicateur
        for idx, row in enumerate(indicateurs, start=1):
            ind_t0 = time.perf_counter()

            # Récupère le “profil” de l’indicateur
            metric = row["Métrique"]
            unite = row["Unité / Détail"]
            keywords = row.get(keywords_tag, "")

            # Pour les logs, on préfère `code_vsme` (ex. B3_1) si présent.
            # Le champ CSV `Code indicateur` peut être plus générique (ex. B3).
            code = row.get("code_vsme") or row.get("Code indicateur") or "NA"
            logger.info(
                "Indicator %s/%s | code=%s | metric=%s | unit=%s",
                idx,
                len(indicateurs),
                code,
                metric,
                unite,
            )
            logger.debug(
                "Indicator details | code=%s | metric=%s | unit=%s", code, metric, unite
            )

            # Traduit les mots-clés si besoin (avec cache par (lang, keywords))
            if lang not in ["en", "fr"] and keywords:
                cache_key = (lang, str(keywords))
                translated = self._keywords_translation_cache.get(cache_key)
                if translated is None:
                    logger.debug(
                        "Keywords translation | cache=miss | lang=%s | keywords=%s",
                        lang,
                        keywords,
                    )
                    promt_conv_lg = (
                        f"Traduit les mots clés de la chaine suivante en langue ISO {lang} : {keywords}\n"
                        "Répond au format : mot1,mot2,mot3,.. \n"
                        "N'ajoute aucune autre information ni remarques.\n"
                        "Si tu ne connais pas la langue, renvoie une chaine vide."
                    )
                    reponse = self.llm.invoke(promt_conv_lg, max_tokens=128)
                    translated = (reponse.get("text", "") or "").strip()
                    # Met aussi en cache une chaîne vide pour éviter de rappeler le LLM
                    self._keywords_translation_cache[cache_key] = translated
                else:
                    logger.debug("Keywords translation | cache=hit | lang=%s", lang)

                if translated:
                    keywords = translated

            # Trace/exports : conserve la requête de retrieval effectivement utilisée.
            # (Utile pour audit/debug, et pour expliquer pourquoi certaines pages ont été sélectionnées.)
            keywords_used = str(keywords or "")

            # Prépare la liste des tokens de mots-clés (ordre stable, sans doublons).
            # On garde un tokeniseur simple (séparateurs non-alphanumériques, min 3 chars)
            # pour rester proche de la logique `count`.
            kw_tokens = [
                t for t in re.split(r"\W+", (keywords_used or "").lower()) if len(t) > 2
            ]
            seen_kw: set[str] = set()
            kw_tokens_unique: list[str] = []
            for t in kw_tokens:
                if t in seen_kw:
                    continue
                seen_kw.add(t)
                kw_tokens_unique.append(t)

            # Sélectionne les extraits/pages les plus pertinents via les mots-clés
            ctx_selected, retrieval_details = find_relevant_snippets_with_details(
                query=str(keywords),
                page_texts=page_texts,
                k=self.top_k_snippets,
                method=self.retrieval_method,
            )
            logger.debug(
                "Retrieval | snippets=%s | method=%s",
                len(ctx_selected),
                self.retrieval_method,
            )

            # Audit : pages candidates / pages conservées + détails des seuils par page.
            pages_candidates = (
                retrieval_details.get("pages_candidates")
                if isinstance(retrieval_details, dict)
                else None
            )
            pages_kept = (
                retrieval_details.get("pages_kept")
                if isinstance(retrieval_details, dict)
                else None
            )
            per_page = (
                retrieval_details.get("per_page")
                if isinstance(retrieval_details, dict)
                else None
            )

            # Mots-clés trouvés : union des mots-clés trouvés sur les pages "passées" (kept)
            found_set: set[str] = set()
            if isinstance(per_page, list):
                for item in per_page:
                    if not isinstance(item, dict):
                        continue
                    if not bool(item.get("passed")):
                        continue
                    for tok in item.get("keywords_found") or []:
                        if isinstance(tok, str) and tok.strip() != "":
                            found_set.add(tok.strip().lower())
            keywords_found_list = [t for t in kw_tokens_unique if t in found_set]
            keywords_found_str = ", ".join(keywords_found_list)

            # Si aucun extrait n'est pertinent
            if not ctx_selected:
                # Si aucune page/extrait n'est jugé pertinent, on renvoie NA et on évite un appel LLM.
                # (Pas de fallback sur le début du document : réduit les faux positifs.)
                logger.info(
                    "No relevant page | method=%s | code=%s | metric=%s -> NA",
                    self.retrieval_method,
                    code,
                    metric,
                )
                results.append(
                    {
                        # Préfère `code_vsme` (ex. B3_1) si présent, sinon fallback sur `Code indicateur` (ex. B3).
                        "Code indicateur": row.get("code_vsme")
                        or row.get("Code indicateur")
                        or "NA",
                        "Thématique": row["Thématique"],
                        "Métrique": row["Métrique"],
                        "Mots clés utilisés": keywords_used,
                        "Mots clés trouvés": "",
                        "Pages candidates": pages_candidates or [],
                        "Pages conservées": pages_kept or [],
                        "Retrieval par page": per_page or [],
                        "Valeur": "NA",
                        "Unité extraite": "NA",
                        "Paragraphe source": "",
                    }
                )
                continue

            # Contexte réellement envoyé au LLM (limité à 6 extraits côté prompt)
            ctx_used = list(ctx_selected[:6])
            context_joined = "\n\n---\n\n".join(ctx_used)
            chars_context = len(context_joined)
            est_tokens_context = max(
                1, int(round(chars_context / 4))
            )  # heuristique ~4 chars/token

            logger.info(
                "Indicator context %s/%s | code=%s | snippets_selected=%s | snippets_used=%s | chars_context=%s | est_tokens_context=%s",
                idx,
                len(indicateurs),
                code,
                len(ctx_selected),
                len(ctx_used),
                chars_context,
                est_tokens_context,
            )

            # Extrait la valeur de l’indicateur à partir du contexte sélectionné
            llm_queried += 1
            data, in_tokens, out_tokens, _ = extract_value_for_metric(
                llm=self.llm,
                metric=metric,
                unite=unite,
                contexte_snippets=ctx_used,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            logger.debug(
                "LLM extract | in_tokens=%s | out_tokens=%s | valeur=%s",
                in_tokens,
                out_tokens,
                data.get("valeur"),
            )

            tot_in_tokens += in_tokens
            tot_out_tokens += out_tokens

            # Comptage "valeur trouvée" : non vide et différent de NA.
            v = str(data.get("valeur") or "").strip()
            if v and v.lower() not in {"na", "n/a"}:
                value_found += 1

            ind_dt = time.perf_counter() - ind_t0
            logger.info(
                "Indicator done %s/%s | code=%s | duration_s=%.3f | valeur=%s | unit=%s",
                idx,
                len(indicateurs),
                code,
                ind_dt,
                data.get("valeur"),
                data.get("unité"),
            )

            results.append(
                {
                    # Préfère `code_vsme` (ex. B3_1) si présent, sinon fallback sur `Code indicateur` (ex. B3).
                    "Code indicateur": row.get("code_vsme")
                    or row.get("Code indicateur")
                    or "NA",
                    "Thématique": row["Thématique"],
                    "Métrique": row["Métrique"],
                    "Mots clés utilisés": keywords_used,
                    "Mots clés trouvés": keywords_found_str,
                    "Pages candidates": pages_candidates or [],
                    "Pages conservées": pages_kept or [],
                    "Retrieval par page": per_page or [],
                    "Valeur": data["valeur"],
                    "Unité extraite": data["unité"],
                    "Paragraphe source": data["paragraphe"],
                }
            )

        t_loop = time.perf_counter() - t0
        logger.info(
            "Step loop_indicators | duration_s=%.3f | indicators=%s",
            t_loop,
            len(indicateurs),
        )

        # Calcule le coût total estimé (à partir des tokens)
        total_cost = (
            EURO_COST_PER_MILLION_INPUT * tot_in_tokens
            + EURO_COST_PER_MILLION_OUTPUT * tot_out_tokens
        ) / 1e6

        # Statistiques à retourner
        stats = ExtractionStats(
            total_indicators=len(indicateurs),
            indicators_llm_queried=llm_queried,
            indicators_value_found=value_found,
            total_input_tokens=tot_in_tokens,
            total_output_tokens=tot_out_tokens,
            total_cost_eur=total_cost,
        )

        t_total = time.perf_counter() - t_total0
        logger.info(
            "END extract_from_pdf | duration_s=%.3f | indicators_total=%s | indicators_llm_queried=%s | indicators_value_found=%s | input_tokens=%s | output_tokens=%s | cost_eur=%.6f",
            t_total,
            stats.total_indicators,
            stats.indicators_llm_queried,
            stats.indicators_value_found,
            stats.total_input_tokens,
            stats.total_output_tokens,
            stats.total_cost_eur,
        )

        # Indicateurs avec leur valeur (NA = non trouvé)
        df = pd.DataFrame(results)

        return df, stats

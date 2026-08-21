"""Points d'entrée CLI.

Note : les tests s'attendent à ce que [`load_dotenv`](vsme_extractor/cli.py:17) existe dans ce module
pour pouvoir le monkeypatcher, même si on ne l'appelle pas directement (on charge `.env` via
`dotenv_values`).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, cast

from dotenv import dotenv_values, find_dotenv, load_dotenv  # noqa: F401

from . import VSMExtractor
from .error_reporting import build_error_report, write_error_report
from .indicators import get_indicators
from .logging_utils import configure_logging, parse_env_bool
from .pdf_loader import load_pdf
from .stats import count_filled_indicators


def _load_rse_mapping(path: Path) -> dict[str, dict[str, str]]:
    """Charge la table de mapping (code_vsme -> champs du portail RSE) pour enrichir la sortie JSON."""
    try:
        import chardet
        import pandas as pd

        raw = path.read_bytes()
        enc = chardet.detect(raw).get("encoding") or "utf-8"
        df = pd.read_csv(path, sep=";", encoding=enc, on_bad_lines="skip")
    except Exception:
        return {}

    if "code_vsme" not in df.columns:
        return {}

    keep = [
        c
        for c in [
            "code_vsme",
            "matched_rse_code",
            "matched_rse_champs_id",
            "matched_rse_colonne_id",
        ]
        if c in df.columns
    ]
    df = df[keep].copy()

    out: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        code = str(row.get("code_vsme") or "").strip()
        if not code:
            continue
        out[code] = {
            "matched_rse_code": str(row.get("matched_rse_code") or "").strip(),
            "matched_rse_champs_id": str(
                row.get("matched_rse_champs_id") or ""
            ).strip(),
            "matched_rse_colonne_id": str(
                row.get("matched_rse_colonne_id") or ""
            ).strip(),
        }
    return out


def _enrich_results_with_rse(
    results: list[dict[str, Any]],
    *,
    rse_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    if not results or not rse_map:
        return results

    for rec in results:
        # Préfère `code_vsme` si présent ; sinon la pipeline l'exporte dans "Code indicateur".
        code = str(
            rec.get("code_vsme") or rec.get("Code indicateur") or rec.get("code") or ""
        ).strip()
        m = rse_map.get(code)
        if not m:
            # Conserve les clés avec valeurs vides (stabilité de schéma).
            rec.setdefault("matched_rse_code", "")
            rec.setdefault("matched_rse_champs_id", "")
            rec.setdefault("matched_rse_colonne_id", "")
            continue
        rec["matched_rse_code"] = m.get("matched_rse_code", "")
        rec["matched_rse_champs_id"] = m.get("matched_rse_champs_id", "")
        rec["matched_rse_colonne_id"] = m.get("matched_rse_colonne_id", "")
    return results


def _strip_retrieval_details(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retire les champs de debug retrieval des lignes indicateurs (pour garder un JSON léger par défaut)."""
    if not results:
        return results
    keys = {"Pages candidates", "Pages conservées", "Retrieval par page"}
    for rec in results:
        for k in keys:
            rec.pop(k, None)
    return results


def build_parser() -> argparse.ArgumentParser:
    """Construit le parser CLI (args + defaults issus de l'environnement)."""
    parser = argparse.ArgumentParser(
        prog="vsme-extract",
        description="Extraction automatique d'indicateurs VSME depuis des rapports PDF.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Chemin vers un fichier PDF ou un dossier contenant des PDFs.",
    )
    parser.add_argument(
        "--count",
        dest="count_dir",
        help="Dossier contenant des fichiers .vsme.xlsx (pour calculer la complétude).",
    )

    parser.add_argument(
        "--export-pages-text",
        action="store_true",
        help=(
            "Exporte le texte extrait de chaque page (numérotée) dans un fichier `.pages.txt` à côté du PDF. "
            "Utile pour debugger l'extraction texte PDF/OCR (l'extraction LLM continue ensuite)."
        ),
    )

    # Format de sortie (xlsx/json)
    env_output_format = (os.getenv("VSME_OUTPUT_FORMAT") or "").strip().lower()
    if env_output_format not in {"xlsx", "json"}:
        env_output_format = "json"
    parser.add_argument(
        "--output-format",
        dest="output_format",
        default=env_output_format,
        choices=["xlsx", "json"],
        help=(
            "Format de sortie. Par défaut: json. Peut aussi être défini via VSME_OUTPUT_FORMAT. "
            "Options: xlsx, json."
        ),
    )

    # Bloc `status` JSON (uniquement pertinent quand output_format=json)
    env_json_status = parse_env_bool(os.getenv("VSME_OUTPUT_JSON_INCLUDE_STATUS"))
    json_status_group = parser.add_mutually_exclusive_group()
    json_status_group.add_argument(
        "--json-include-status",
        dest="json_include_status",
        action="store_true",
        help=(
            "Inclut le bloc `status` dans le JSON. Par défaut: activé. "
            "Peut aussi être défini via VSME_OUTPUT_JSON_INCLUDE_STATUS=1."
        ),
    )
    json_status_group.add_argument(
        "--json-no-status",
        dest="json_include_status",
        action="store_false",
        help=(
            "Exclut le bloc `status` du JSON. Peut aussi être défini via VSME_OUTPUT_JSON_INCLUDE_STATUS=0."
        ),
    )
    parser.set_defaults(
        json_include_status=(
            bool(env_json_status) if env_json_status is not None else True
        )
    )

    # Méthode de retrieval (sélection des extraits/pages avant appel LLM)
    env_retrieval = (os.getenv("VSME_RETRIEVAL_METHOD") or "count").strip()
    parser.add_argument(
        "--retrieval-method",
        dest="retrieval_method",
        default=env_retrieval,
        choices=[
            "count",
            "count_refine",
        ],
        help=(
            "Méthode de sélection des extraits/pages avant appel LLM. "
            "Par défaut: count. Peut aussi être définie via VSME_RETRIEVAL_METHOD. "
            "Options: count, count_refine."
        ),
    )

    # Option JSON : inclure les détails de debug retrieval dans chaque ligne indicateur
    env_json_retrieval = parse_env_bool(
        os.getenv("VSME_OUTPUT_JSON_INCLUDE_RETRIEVAL_DETAILS")
    )
    json_ret_group = parser.add_mutually_exclusive_group()
    json_ret_group.add_argument(
        "--json-include-retrieval-details",
        dest="json_include_retrieval_details",
        action="store_true",
        help=(
            "Inclut dans le JSON, pour chaque indicateur, les champs de debug retrieval: "
            "'Pages candidates', 'Pages conservées', 'Retrieval par page'. "
            "Peut aussi être défini via VSME_OUTPUT_JSON_INCLUDE_RETRIEVAL_DETAILS=1."
        ),
    )
    json_ret_group.add_argument(
        "--json-no-retrieval-details",
        dest="json_include_retrieval_details",
        action="store_false",
        help=(
            "Exclut du JSON les champs de debug retrieval (par défaut). "
            "Peut aussi être défini via VSME_OUTPUT_JSON_INCLUDE_RETRIEVAL_DETAILS=0."
        ),
    )
    parser.set_defaults(
        json_include_retrieval_details=(
            bool(env_json_retrieval) if env_json_retrieval is not None else False
        )
    )

    parser.add_argument(
        "--codes",
        dest="code_vsme_list",
        default=None,
        help=(
            "Liste de codes `code_vsme` à extraire (surcharge VSME_CODE_VSME_LIST si fourni). "
            "Séparateurs acceptés : virgule, point-virgule, espaces. "
            "Exemple: --codes B3_1,B3_2,C1_1. "
            "Valeur spéciale: --codes all (ou '*') pour extraire tous les indicateurs (désactive le filtre `defaut==1`)."
        ),
    )
    list_group = parser.add_mutually_exclusive_group()
    list_group.add_argument(
        "--list-current-indicators",
        action="store_true",
        help=(
            "Affiche la liste des indicateurs actuellement utilisés par l’extracteur "
            "(après application des variables d’environnement), sous la forme: code_vsme + métrique, "
            "triés par code_vsme."
        ),
    )
    list_group.add_argument(
        "--list-all-indicators",
        action="store_true",
        help=(
            "Affiche la liste complète des indicateurs du CSV (sans filtre `.env`), sous la forme: "
            "code_vsme + métrique, triés par code_vsme."
        ),
    )

    # Valeurs par défaut du logging (peuvent venir des variables d'environnement)
    # - SME_LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
    # - VSME_LOG_FILE: chemin
    # - VSME_LOG_STDOUT: 1/0, true/false, yes/no, on/off
    env_level = os.getenv("SME_LOG_LEVEL") or "INFO"
    env_file = os.getenv("VSME_LOG_FILE") or None
    env_stdout = parse_env_bool(os.getenv("VSME_LOG_STDOUT"))

    parser.add_argument(
        "--log-level",
        default=env_level,
        help="Niveau de logs (DEBUG, INFO, WARNING, ERROR). Peut aussi être défini via SME_LOG_LEVEL.",
    )
    parser.add_argument(
        "--log-file",
        default=env_file,
        help="Chemin d'un fichier log (optionnel). Peut aussi être défini via VSME_LOG_FILE.",
    )
    stdout_group = parser.add_mutually_exclusive_group()
    stdout_group.add_argument(
        "--log-stdout",
        dest="log_stdout",
        action="store_true",
        help="Activer les logs sur stdout (par défaut). Peut aussi être défini via VSME_LOG_STDOUT.",
    )
    stdout_group.add_argument(
        "--no-log-stdout",
        dest="log_stdout",
        action="store_false",
        help="Désactiver les logs sur stdout. Peut aussi être défini via VSME_LOG_STDOUT.",
    )
    parser.set_defaults(log_stdout=(env_stdout if env_stdout is not None else True))

    return parser


def main(argv: list[str] | None = None) -> None:
    """Entrée CLI installable (console_scripts)."""
    # Charge `.env` (en recherchant depuis le répertoire courant vers les parents).
    #
    # Politique :
    # - Une variable déjà définie dans l'environnement (export / prefix de commande)
    #   garde priorité si elle est NON vide.
    # - Si une variable est absente OU vide dans l'environnement, on la remplit depuis `.env`.
    #
    # Objectif :
    # - permettre `VSME_LOG_FILE=... vsme-extract ...` (env explicite) sans être écrasé par `.env`
    # - éviter le piège d'une variable exportée mais vide qui masquerait `.env`.
    dotenv_path = find_dotenv(usecwd=True)
    dotenv_loaded = False
    if dotenv_path:
        try:
            values = dotenv_values(dotenv_path)
            for k, v in values.items():
                if v is None:
                    continue
                cur = os.getenv(k)
                if cur is None or str(cur).strip() == "":
                    # Ne pas écraser une valeur déjà présente et non vide.
                    os.environ[k] = str(v)
            dotenv_loaded = True
        except Exception:
            dotenv_loaded = False

    parser = build_parser()
    ns = parser.parse_args(argv)

    # Option CLI : la liste de codes fournie surcharge la variable d'environnement.
    # Cela permet d'utiliser un `.env` générique tout en forçant une sélection ponctuelle.
    if ns.code_vsme_list is not None and str(ns.code_vsme_list).strip() != "":
        os.environ["VSME_CODE_VSME_LIST"] = str(ns.code_vsme_list).strip()

    configure_logging(
        level=ns.log_level,
        log_to_stdout=ns.log_stdout,
        log_file=ns.log_file,
        reset_handlers=True,
    )
    logger = logging.getLogger(__name__)

    # Diagnostic : confirme quel `.env` a été trouvé/chargé et l'état des variables
    # de filtrage des indicateurs.
    # (Ne jamais logger de secrets.)
    logger.info(
        "dotenv | found=%s | loaded=%s | cwd=%s",
        dotenv_path or None,
        dotenv_loaded,
        str(Path.cwd()),
    )
    logger.info(
        "env | SCW_API_KEY_set=%s | VSM_INDICATORS_PATH=%s | VSME_CODE_VSME_LIST=%s",
        bool(os.getenv("SCW_API_KEY")),
        (os.getenv("VSM_INDICATORS_PATH") or "").strip() or None,
        (os.getenv("VSME_CODE_VSME_LIST") or "").strip() or None,
    )

    # ===============================
    # LIST INDICATORS
    # ===============================
    if ns.list_current_indicators or ns.list_all_indicators:
        indicators = get_indicators(apply_env_filter=bool(ns.list_current_indicators))
        items = []
        for row in indicators:
            code_vsme = str(row.get("code_vsme") or "").strip()
            metric = str(row.get("Métrique") or row.get("Metrique") or "").strip()
            code_ind = str(row.get("Code indicateur") or "").strip()
            items.append((code_vsme, metric, code_ind))

        def _code_sort_key(code: str) -> tuple:
            """Clé de tri pour des codes du type B1, B10, C8_1.

            Ordre : lettre(s), puis partie numérique (int), puis suffixe optionnel `_indice` (int).
            """
            s = (code or "").strip()
            m = re.match(r"^([A-Za-z]+)(\d+)(?:_(\d+))?$", s)
            if not m:
                # Met les codes non conformes à la fin (fallback lexical)
                return ("~", 10**9, 10**9, s)
            letters = m.group(1).upper()
            num = int(m.group(2))
            idx = int(m.group(3)) if m.group(3) is not None else 0
            return (letters, num, idx, s)

        def _row_sort_key(t: tuple[str, str, str]) -> tuple:
            """Clé de tri globale pour une ligne (priorité au code_vsme)."""
            code_vsme, metric, code_ind = t
            # Préfère `code_vsme` si présent ; sinon fallback sur `Code indicateur`.
            primary = code_vsme or code_ind
            return (
                _code_sort_key(primary),
                _code_sort_key(code_vsme),
                _code_sort_key(code_ind),
                metric,
            )

        items.sort(key=_row_sort_key)

        print("code_vsme\tCode indicateur\tMétrique")
        for code_vsme, metric, code_ind in items:
            print(f"{code_vsme}\t{code_ind}\t{metric}")
        return

    # ===============================
    # CHECK OPTION --count
    # ===============================
    if ns.count_dir:
        results_dir = Path(ns.count_dir)
        if not results_dir.exists():
            logger.error("Erreur : dossier introuvable : %s", results_dir)
            raise SystemExit(1)

        logger.info("=== Comptage de complétude dans : %s ===", results_dir)
        df_stats = count_filled_indicators(results_dir)

        out_path = results_dir / "stats_completude.xlsx"
        df_stats.to_excel(out_path, index=False)

        logger.info("Résultats → %s", out_path)
        logger.info("\n%s", df_stats.to_string(index=False))
        return

    # ===============================
    # MODE EXTRACTION
    # ===============================
    if not ns.target:
        logger.error("Argument manquant: target (fichier.pdf ou dossier/)")
        logger.info("\n%s", parser.format_help())
        raise SystemExit(1)

    target = Path(ns.target)
    if not target.exists():
        logger.error("Erreur : chemin introuvable : %s", target)
        raise SystemExit(1)

    # ===============================
    # DEBUG OPTION: EXPORT PAGE TEXTS
    # ===============================
    export_pages_text = bool(ns.export_pages_text)

    def _dump_pdf_pages(pdf: Path) -> None:
        """Exporte le texte des pages pour debug, sans interrompre le traitement principal."""
        pages, page_texts, _ = load_pdf(pdf)
        out_path = pdf.with_suffix(".pages.txt")
        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"PDF: {pdf}\n")
            f.write(f"Pages: {len(page_texts)}\n\n")
            for i, txt in enumerate(page_texts, start=1):
                t = txt or ""
                f.write(f"===== PAGE {i} / {len(page_texts)} | chars={len(t)} =====\n")
                f.write(t)
                if not t.endswith("\n"):
                    f.write("\n")
                f.write("\n")
        logger.info("Pages text exported: %s", out_path)

    log_tb = (os.getenv("VSME_LOG_TRACEBACK") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }

    extractor = None
    try:
        extractor = VSMExtractor(retrieval_method=ns.retrieval_method)
    except Exception as e:
        # Init peut échouer (healthcheck LLM, config, etc.).
        # On évite d'afficher un traceback en console : le détail est dans un rapport JSON.
        logger.error(
            "Extractor init failed | error=%s: %s",
            e.__class__.__name__,
            str(e),
            exc_info=(True if log_tb else False),
        )

        # Écrit un rapport d'erreur global (si on a un dossier) ou à côté du PDF.
        if target.is_dir():
            report_path = target / "vsme_extract.error.json"
            payload = build_error_report(
                exc=e,
                stage="init",
                pdf=None,
                extractor=None,
                extra={"target": str(target)},
            )
        else:
            report_path = target.with_suffix(".vsme.error.json")
            payload = build_error_report(
                exc=e,
                stage="init",
                pdf=str(target),
                extractor=None,
            )

        write_error_report(report_path, payload)
        logger.error("Error report written: %s", report_path)
        raise SystemExit(2)

    # Format de sortie (la valeur CLI est prioritaire ; défaut = json)
    output_format = (getattr(ns, "output_format", None) or "json").strip().lower()
    if output_format not in {"xlsx", "json"}:
        output_format = "json"

    include_json_status = (
        bool(getattr(ns, "json_include_status", True))
        if output_format == "json"
        else False
    )

    include_json_retrieval_details = (
        bool(getattr(ns, "json_include_retrieval_details", False))
        if output_format == "json"
        else False
    )

    # Enrichissement optionnel pour les sorties JSON (code_vsme -> champs portail RSE)
    rse_map: dict[str, dict[str, str]] = {}
    if output_format == "json":
        rse_path = Path(__file__).parent / "data" / "table_codes_portail_rse.csv"
        if rse_path.exists():
            rse_map = _load_rse_mapping(rse_path)

    def _missing_requested_codes(codes_raw: str | None) -> list[str] | None:
        """Retourne la liste (ordonnée) des codes demandés absents du référentiel indicateurs."""
        if codes_raw is None:
            return None
        codes_raw = str(codes_raw).strip()
        if codes_raw == "":
            return None

        requested = [c.strip() for c in re.split(r"[\s,;]+", codes_raw) if c.strip()]
        if not requested:
            return None

        try:
            all_rows = get_indicators(apply_env_filter=False)
            available = {
                str(r.get("code_vsme") or "").strip()
                for r in all_rows
                if r.get("code_vsme")
            }
        except Exception:
            return None

        missing = [c for c in requested if c not in available]
        return missing or []

    # -------- Un fichier PDF --------
    if target.is_file() and target.suffix.lower() == ".pdf":
        logger.info("PDF: %s", target)
        logger.info("=== Extraction (single) : %s ===", target.name)

        if export_pages_text:
            try:
                _dump_pdf_pages(target)
            except Exception as e:
                logger.warning(
                    "--export-pages-text failed (continuing extraction) | pdf=%s | error=%s: %s",
                    str(target),
                    e.__class__.__name__,
                    str(e),
                )

        # Trace l'état des filtres réellement appliqués (utile pour interpréter un JSON partiel).
        code_list_effective = (os.getenv("VSME_CODE_VSME_LIST") or "").strip() or None
        indicators_path_effective = (
            os.getenv("VSM_INDICATORS_PATH") or ""
        ).strip() or None
        missing_codes = _missing_requested_codes(code_list_effective)

        try:
            df, stats = extractor.extract_from_pdf(str(target))
            extraction_error = None
            completed = True
        except Exception as e:
            df = None
            stats = None
            extraction_error = {
                "type": e.__class__.__name__,
                "message": str(e),
            }
            completed = False

            # Rapport d'erreur à côté du PDF (évite d'inonder la console).
            report_path = target.with_suffix(".vsme.error.json")
            payload = build_error_report(
                exc=e,
                stage="extract",
                pdf=str(target),
                extractor=extractor,
            )
            write_error_report(report_path, payload)
            logger.error(
                "Extraction failed | pdf=%s | error=%s: %s | report=%s",
                str(target),
                e.__class__.__name__,
                str(e),
                str(report_path),
                exc_info=(True if log_tb else False),
            )

        if output_format == "json":
            out_path = target.with_suffix(".vsme.json")
            payload: dict[str, object] = {"pdf": str(target)}
            if include_json_status:
                payload["status"] = {
                    "completed": completed,
                    "error": extraction_error,
                    "error_report": (
                        str(target.with_suffix(".vsme.error.json"))
                        if not completed
                        else None
                    ),
                    "filters": {
                        "VSME_CODE_VSME_LIST": code_list_effective,
                        "VSM_INDICATORS_PATH": indicators_path_effective,
                    },
                    "missing_codes": missing_codes,
                }
            results: list[dict[str, Any]] = (
                []
                if df is None
                else cast(list[dict[str, Any]], df.to_dict(orient="records"))
            )
            if not include_json_retrieval_details:
                results = _strip_retrieval_details(results)
            payload["results"] = _enrich_results_with_rse(results, rse_map=rse_map)
            payload["stats"] = (
                None
                if stats is None
                else {
                    "total_indicators": getattr(stats, "total_indicators", None),
                    "indicators_llm_queried": getattr(
                        stats, "indicators_llm_queried", None
                    ),
                    "indicators_value_found": getattr(
                        stats, "indicators_value_found", None
                    ),
                    "total_input_tokens": stats.total_input_tokens,
                    "total_output_tokens": stats.total_output_tokens,
                    "total_cost_eur": stats.total_cost_eur,
                }
            )
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            if df is None or stats is None:
                logger.error(
                    "Extraction échouée, aucun export Excel produit | error=%s",
                    extraction_error,
                )
                raise SystemExit(2)
            out_path = target.with_suffix(".vsme.xlsx")
            df.to_excel(out_path, index=False)

        logger.info("Export: %s", out_path)
        if stats is not None:
            logger.info("Tokens input : %s", stats.total_input_tokens)
            logger.info("Tokens output: %s", stats.total_output_tokens)
            logger.info("Coût total   : %.4f €", stats.total_cost_eur)
            logger.info("=== Extraction terminée : %s ===", target.name)
        else:
            logger.error("=== Extraction interrompue : %s ===", target.name)
            raise SystemExit(2)
        return

    # -------- Un dossier --------
    if target.is_dir():
        pdfs = list(target.glob("*.pdf"))
        if not pdfs:
            logger.warning("Aucun PDF trouvé dans %s", target)
            return

        for pdf in pdfs:
            logger.info("PDF: %s", pdf)
            logger.info("=== Extraction : %s ===", pdf.name)

            if export_pages_text:
                try:
                    _dump_pdf_pages(pdf)
                except Exception as e:
                    logger.warning(
                        "--export-pages-text failed (continuing extraction) | pdf=%s | error=%s: %s",
                        str(pdf),
                        e.__class__.__name__,
                        str(e),
                    )
            code_list_effective = (
                os.getenv("VSME_CODE_VSME_LIST") or ""
            ).strip() or None
            indicators_path_effective = (
                os.getenv("VSM_INDICATORS_PATH") or ""
            ).strip() or None
            missing_codes = _missing_requested_codes(code_list_effective)

            try:
                df, stats = extractor.extract_from_pdf(str(pdf))
                extraction_error = None
                completed = True
            except Exception as e:
                df = None
                stats = None
                extraction_error = {
                    "type": e.__class__.__name__,
                    "message": str(e),
                }
                completed = False

                report_path = pdf.with_suffix(".vsme.error.json")
                payload_err = build_error_report(
                    exc=e,
                    stage="extract",
                    pdf=str(pdf),
                    extractor=extractor,
                )
                write_error_report(report_path, payload_err)
                logger.error(
                    "Extraction failed | pdf=%s | error=%s: %s | report=%s",
                    str(pdf),
                    e.__class__.__name__,
                    str(e),
                    str(report_path),
                    exc_info=(True if log_tb else False),
                )

            if output_format == "json":
                out_path = pdf.with_suffix(".vsme.json")
                payload: dict[str, object] = {"pdf": str(pdf)}
                if include_json_status:
                    payload["status"] = {
                        "completed": completed,
                        "error": extraction_error,
                        "error_report": (
                            str(pdf.with_suffix(".vsme.error.json"))
                            if not completed
                            else None
                        ),
                        "filters": {
                            "VSME_CODE_VSME_LIST": code_list_effective,
                            "VSM_INDICATORS_PATH": indicators_path_effective,
                        },
                        "missing_codes": missing_codes,
                    }
                results: list[dict[str, Any]] = (
                    []
                    if df is None
                    else cast(list[dict[str, Any]], df.to_dict(orient="records"))
                )
                if not include_json_retrieval_details:
                    results = _strip_retrieval_details(results)
                payload["results"] = _enrich_results_with_rse(results, rse_map=rse_map)
                payload["stats"] = (
                    None
                    if stats is None
                    else {
                        "total_indicators": getattr(stats, "total_indicators", None),
                        "indicators_llm_queried": getattr(
                            stats, "indicators_llm_queried", None
                        ),
                        "indicators_value_found": getattr(
                            stats, "indicators_value_found", None
                        ),
                        "total_input_tokens": stats.total_input_tokens,
                        "total_output_tokens": stats.total_output_tokens,
                        "total_cost_eur": stats.total_cost_eur,
                    }
                )
                out_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            else:
                if df is None or stats is None:
                    logger.error(
                        "Extraction échouée, aucun export Excel produit | pdf=%s | error=%s",
                        pdf,
                        extraction_error,
                    )
                    continue
                out_path = pdf.with_suffix(".vsme.xlsx")
                df.to_excel(out_path, index=False)

            logger.info("Export: %s", out_path)
            if stats is not None:
                logger.info("Tokens input : %s", stats.total_input_tokens)
                logger.info("Tokens output: %s", stats.total_output_tokens)
                logger.info("Coût total   : %.4f €", stats.total_cost_eur)
                logger.info("=== Extraction terminée : %s ===", pdf.name)
            else:
                logger.error("=== Extraction interrompue : %s ===", pdf.name)

        return


if __name__ == "__main__":
    main()

import logging

import openai

from pathlib import Path
from typing import Any, cast

from helpers.notifications import make_status
from helpers.notifications import notify_app

from .indicators import get_indicators
from .pipeline import ExtractionStats
from .pipeline import VSMExtractor
from .cli import _enrich_results_with_rse
from .cli import _load_rse_mapping


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def analyser(document_id, pdf_dir_path, callback_url):
    notify_app(callback_url, make_status(document_id, "processing"))
    pdf_path = Path(pdf_dir_path) / "fichier.pdf"
    try:
        extractor = VSMExtractor(retrieval_method="count") # passer à count_refine?
        df, stats = extractor.extract_from_pdf(pdf_path)
    except openai.PermissionDeniedError: # problème de connexion au LLM
        notify_app(
            callback_url,
            make_status(
                document_id,
                "error",
                msg="Erreur de connexion"
            )
        )
        return

    if df is None or stats is None or stats.indicators_value_found == 0:
        # "Extraction échouée
        notify_app(
            callback_url,
            make_status(
                document_id,
                "error",
                msg="Aucune phrase trouvée dans le PDF"
            )
        )
        return

    results: list[dict[str, Any]] = (
                    []
                    if df is None
                    else cast(list[dict[str, Any]], df.to_dict(orient="records"))
                )

    rse_path = Path("./data/table_codes_portail_rse.csv")
    rse_map = _load_rse_mapping(rse_path)
    results = _enrich_results_with_rse(results, rse_map=rse_map)
    #payload cli.py ligne 621
    notify_app(callback_url, make_status(document_id, "success", resultat_json=results))

    logger.info(f"fin de traitement v2 pour le fichier {document_id} ({pdf_path})")

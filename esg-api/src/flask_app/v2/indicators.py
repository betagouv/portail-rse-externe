from __future__ import annotations

import logging
import os
import re
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, cast

import chardet
import pandas as pd

logger = logging.getLogger(__name__)

PACKAGE_DATA_MODULE = "v2"
PACKAGE_CSV_NAME = "indicateurs_vsme.csv"
DEFAULT_INDICATORS_PATH = Path(__file__).parent / "data" / PACKAGE_CSV_NAME


def get_indicators(
    path: str | Path | None = None,
    *,
    apply_env_filter: bool = True,
) -> List[Dict[str, Any]]:
    """Charge la liste des indicateurs depuis un CSV.

    Le CSV est lu depuis les données packagées (voir `PACKAGE_CSV_NAME`).

    Filtrage (si `apply_env_filter=True`) :
    - si `VSME_CODE_VSME_LIST` est non vide : filtre sur les `code_vsme` listés
    - sinon : filtre sur `defaut == 1`
    """
    path = DEFAULT_INDICATORS_PATH

    def detect_encoding(p: str | Path):
        """Détecte l'encodage d'un fichier via `chardet`."""
        with open(p, "rb") as f:
            raw = f.read()
        return chardet.detect(raw)

    info = detect_encoding(path)

    df = pd.read_csv(
        path,
        sep=";",
        encoding=info.get("encoding"),
        on_bad_lines="skip",
    )

    if apply_env_filter:
        # Filtrage optionnel par `code_vsme` via .env
        # - Si VSME_CODE_VSME_LIST est défini et non vide : conserver uniquement ces `code_vsme`
        # - Sinon (absent/vide) : conserver uniquement les lignes où `defaut` == 1
        codes_raw = (os.getenv("VSME_CODE_VSME_LIST") or "").strip()
        if codes_raw:
            # Valeur spéciale : "all" (ou "*") désactive le filtrage et conserve tous les indicateurs.
            # Utile côté CLI : `--codes all`.
            if codes_raw.lower() in {"all", "*"}:
                records = df.to_dict(orient="records")  # type: ignore[call-overload]
                return cast(List[Dict[str, Any]], records)
            if "code_vsme" not in df.columns:
                logger.warning(
                    "VSME_CODE_VSME_LIST est défini mais la colonne 'code_vsme' est absente du CSV (%s). Aucun filtrage appliqué.",
                    path,
                )
            else:
                codes = [
                    c.strip() for c in re.split(r"[\s,;]+", codes_raw) if c.strip()
                ]
                df = df[df["code_vsme"].astype(str).isin(codes)]
        else:
            if "defaut" in df.columns:
                df = df[df["defaut"].astype(str).str.strip() == "1"]
            else:
                logger.warning(
                    "VSME_CODE_VSME_LIST est vide/absent et la colonne 'defaut' est absente du CSV (%s). Aucun filtrage appliqué.",
                    path,
                )

    records = df.to_dict(orient="records")  # type: ignore[call-overload]
    return cast(List[Dict[str, Any]], records)

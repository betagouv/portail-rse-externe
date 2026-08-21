import logging
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

logger = logging.getLogger(__name__)


def _is_filled(value) -> bool:
    """Retourne True si la valeur est considérée comme renseignée."""
    if pd.isna(value):
        return False

    s = str(value).strip()
    if s == "":
        return False

    if s.upper() in {"NA", "N/A", "NONE", "NULL", "NAN"}:
        return False

    return True


def count_filled_indicators(results_dir: str | Path) -> pd.DataFrame:
    """
    Analyse tous les fichiers .vsme.xlsx et/ou .vsme.json d'un répertoire et compte,
    pour chaque métrique, dans combien de fichiers la colonne 'Valeur' est renseignée.

    Ajoute également :
      - Code indicateur
      - Thématique
    """

    results_dir = Path(results_dir)
    result_files = sorted(results_dir.glob("*.vsme.xlsx")) + sorted(
        results_dir.glob("*.vsme.json")
    )

    if not result_files:
        raise FileNotFoundError(
            f"Aucun fichier .vsme.xlsx ou .vsme.json trouvé dans : {results_dir}"
        )

    # Structure de stockage :
    # key = (Code indicateur, Métrique)
    # value = dict avec code, thématique, métrique, compte, nb_fichiers
    stats: Dict[tuple, Dict[str, Any]] = {}

    for f in result_files:
        if f.suffix.lower() == ".xlsx":
            try:
                # Spécifie explicitement l'engine pour éviter les erreurs de détection.
                df = pd.read_excel(f, engine="openpyxl")
            except Exception:
                logger.warning("Fichier ignoré (Excel illisible) : %s", f.name)
                continue
        elif f.suffix.lower() == ".json":
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
                rows = payload.get("results")
                if not isinstance(rows, list):
                    logger.warning("Fichier ignoré (JSON invalide) : %s", f.name)
                    continue
                df = pd.DataFrame(rows)
            except Exception:
                logger.warning("Fichier ignoré (JSON illisible) : %s", f.name)
                continue
        else:
            continue

        # Vérif colonnes minimales
        required_cols = {"Code indicateur", "Thématique", "Métrique", "Valeur"}
        if not required_cols.issubset(df.columns):
            logger.warning("Fichier ignoré (colonnes manquantes) : %s", f.name)
            continue

        # Pour savoir dans combien de fichiers apparaît chaque clé
        seen_this_file = set()

        for _, row in df.iterrows():
            code = str(row["Code indicateur"]).strip()
            theme = str(row["Thématique"]).strip()
            metric = str(row["Métrique"]).strip()
            value = row["Valeur"]

            if metric == "":
                continue

            key = (code, metric)

            if key not in stats:
                stats[key] = {
                    "Code indicateur": code,
                    "Thématique": theme,
                    "Métrique": metric,
                    "Occurrences renseignées": 0,
                    "Fichiers contenant la métrique": 0,
                }

            # Comptage du nombre de fichiers où la métrique apparaît
            if key not in seen_this_file:
                stats[key]["Fichiers contenant la métrique"] += 1
                seen_this_file.add(key)

            # Comptage des valeurs renseignées
            if _is_filled(value):
                stats[key]["Occurrences renseignées"] += 1

    # Construction du DataFrame résultat
    rows = []
    for key, info in stats.items():
        filled_count = info["Occurrences renseignées"]
        total_with_metric = info["Fichiers contenant la métrique"] or 1  # éviter /0
        completeness = round(100 * filled_count / total_with_metric, 2)

        rows.append(
            {
                "Code indicateur": info["Code indicateur"],
                "Thématique": info["Thématique"],
                "Métrique": info["Métrique"],
                "Occurrences renseignées": filled_count,
                "Fichiers contenant la métrique": total_with_metric,
                "% complétude (parmi fichiers où présente)": completeness,
            }
        )

    if not rows:
        # Aucun fichier exploitable (ex. fichiers présents mais ignorés car colonnes manquantes).
        return pd.DataFrame(
            columns=[
                "Code indicateur",
                "Thématique",
                "Métrique",
                "Occurrences renseignées",
                "Fichiers contenant la métrique",
                "% complétude (parmi fichiers où présente)",
            ]
        )

    result_df = pd.DataFrame(rows)

    # --- Extraire l'indice numérique à partir du code 'Bxx' ---
    def extract_num(code: str) -> int:
        """Extrait la partie numérique d'un code (ex. B3 -> 3) pour un tri naturel."""
        try:
            return int(str(code)[1:])  # B3 → 3
        except Exception:
            return 9999  # sécurité

    result_df["Index tri"] = result_df["Code indicateur"].apply(extract_num)

    # Tri naturel : B1 < B2 < ... < B9 < B10 < ...
    result_df = result_df.sort_values(
        by=["Index tri", "Métrique"], ascending=[True, True], ignore_index=True
    )

    # Retirer la colonne technique
    result_df = result_df.drop(columns=["Index tri"])

    return result_df

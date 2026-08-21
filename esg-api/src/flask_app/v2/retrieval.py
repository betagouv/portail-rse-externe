from __future__ import annotations

from collections import Counter
import logging
import math
import re
import unicodedata
from typing import Callable, List, Literal, Sequence

from .config import VSME_RETRIEVAL_ABS_THR, VSME_RETRIEVAL_REL_THR


logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Tokenise un texte en mots (min 3 caractères), en minuscules."""
    return [t for t in re.split(r"\W+", (text or "").lower()) if len(t) > 2]


_SUBSCRIPT_DIGITS = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
    }
)


def _normalize_text_soft(text: str) -> str:
    """Normalisation légère pour améliorer la robustesse (Unicode/OCR/tirets).

    Objectif : se rapprocher de la tolérance du matching substring (mode `count`)
    tout en restant dans un cadre "token-based" compatible BM25.
    """
    t = text or ""

    # Normalisation Unicode (ex. compatibilité) + conversion des chiffres en indice.
    t = unicodedata.normalize("NFKC", t).translate(_SUBSCRIPT_DIGITS)

    # Supprime les césures de fin de ligne (classique OCR/PDF) : "emis-\nsions" -> "emissions".
    t = re.sub(r"([A-Za-z])\-\s*\n\s*([A-Za-z])", r"\1\2", t)

    # Harmonise les tirets (– — −) en '-'.
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")

    # Aplatis les retours ligne.
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def _strip_accents(text: str) -> str:
    """Retire les diacritiques (é -> e) pour tolérer les variations OCR."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _tokenize_soft(text: str) -> list[str]:
    """Tokenisation plus permissive que [`_tokenize()`](vsme_extractor/retrieval.py:8).

    Principes :
    - normalisation Unicode/OCR
    - gestion des tirets ("scope-1" ~ "scope 1" ~ "scope1")
    - retrait des accents (tolérance OCR)

    Notes :
    - On garde des tokens de longueur >= 2 (utile pour "co2", "s1" etc.).
    - On génère des variantes sans tiret pour retrouver du signal que `count` capte en substring.
    """
    base = _normalize_text_soft(text)
    base = _strip_accents(base)

    # 1) version avec tirets remplacés par espace (tokenisation classique)
    v1 = base.replace("-", " ")
    toks1 = re.findall(r"[a-z0-9]{2,}", v1)

    # 2) version avec tirets supprimés (pour matcher "scope-1" vs "scope1")
    v2 = base.replace("-", "")
    toks2 = re.findall(r"[a-z0-9]{2,}", v2)

    # Dé-duplication tout en gardant un ordre stable (pour debug).
    seen: set[str] = set()
    out: list[str] = []
    for tok in [*toks1, *toks2]:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _count_scores(query: str, page_texts: List[str]) -> list[tuple[int, int, str]]:
    """Scores `count` (substring) : retourne [(score, i, txt)] trié décroissant."""
    tokens = _tokenize(query)
    if not tokens or not page_texts:
        return []

    scores: list[tuple[int, int, str]] = []
    for i, txt in enumerate(page_texts):
        t = (txt or "").lower()
        score = sum(t.count(tok) for tok in tokens)
        if score > 0:
            scores.append((score, i, txt))

    scores.sort(reverse=True, key=lambda x: x[0])
    return scores


def _word_ngrams(
    tokens: Sequence[str], ngram_range: tuple[int, int] = (1, 3)
) -> list[str]:
    """Construit des n-grams de mots à partir d'une liste de tokens.

    On conserve les unigrams + des n-grams plus longs pour capturer des expressions
    (ex. "emissions scope3").

    Détails d'implémentation :
    - les n-grams sont joints avec un espace simple (lisible et stable)
    - les doublons sont conservés (la TF tient compte des répétitions)
    """

    if not tokens:
        return []

    n_min, n_max = ngram_range
    n_min = max(1, int(n_min))
    n_max = max(n_min, int(n_max))

    out: list[str] = []
    toks = list(tokens)
    n_toks = len(toks)
    for n in range(n_min, n_max + 1):
        if n > n_toks:
            break
        for i in range(0, n_toks - n + 1):
            out.append(" ".join(toks[i : i + n]))
    return out


def _tfidf_ngram_scores(
    *,
    query: str,
    page_texts: List[str],
    tokenize: Callable[[str], list[str]],
    ngram_range: tuple[int, int] = (1, 3),
    candidate_indices: set[int] | None = None,
) -> list[tuple[float, int, str]]:
    """Similarité cosinus TF‑IDF sur des n-grams de mots.

    Retourne une liste de (score, page_index, text) triée par score décroissant.

    Notes :
    - Pas de dépendance externe (sans sklearn).
    - IDF lissée : log((N + 1)/(df + 1)) + 1.
    - TF sous-linéaire : 1 + log(tf).
    - Si `candidate_indices` est fourni, on score uniquement ces documents, mais DF/IDF
      restent calculés sur toutes les pages (stabilité).
    """

    if not query or not page_texts:
        return []

    # ---- Construit les TF par document et la DF globale sur les n-grams
    doc_tfs: list[Counter[str]] = []
    df: Counter[str] = Counter()

    for txt in page_texts:
        toks = tokenize(txt)
        grams = _word_ngrams(toks, ngram_range=ngram_range)
        tf = Counter(grams)
        doc_tfs.append(tf)
        df.update(tf.keys())

    n_docs = len(page_texts)
    if n_docs <= 0:
        return []

    def idf(term: str) -> float:
        return math.log((n_docs + 1.0) / (float(df.get(term, 0)) + 1.0)) + 1.0

    # ---- Query weights
    q_toks = tokenize(query)
    q_grams = _word_ngrams(q_toks, ngram_range=ngram_range)
    q_tf = Counter(q_grams)
    if not q_tf:
        return []

    q_w: dict[str, float] = {}
    q_norm2 = 0.0
    for term, tf in q_tf.items():
        if tf <= 0:
            continue
        w = (1.0 + math.log(float(tf))) * idf(term)
        q_w[term] = w
        q_norm2 += w * w
    q_norm = math.sqrt(q_norm2) if q_norm2 > 0 else 0.0
    if q_norm <= 0:
        return []

    # ---- Document norms (full) + cosine scores on candidates
    scores: list[tuple[float, int, str]] = []
    for i, (txt, tf) in enumerate(zip(page_texts, doc_tfs)):
        if candidate_indices is not None and i not in candidate_indices:
            continue
        if not tf:
            continue

        # Full doc norm (all terms)
        d_norm2 = 0.0
        for term, c in tf.items():
            if c <= 0:
                continue
            w = (1.0 + math.log(float(c))) * idf(term)
            d_norm2 += w * w
        d_norm = math.sqrt(d_norm2) if d_norm2 > 0 else 0.0
        if d_norm <= 0:
            continue

        # Dot-product only on query terms
        dot = 0.0
        for term, qwt in q_w.items():
            c = tf.get(term, 0)
            if c <= 0:
                continue
            dwt = (1.0 + math.log(float(c))) * idf(term)
            dot += qwt * dwt

        score = dot / (q_norm * d_norm) if dot > 0 else 0.0
        if score > 0:
            scores.append((score, i, txt))

    scores.sort(reverse=True, key=lambda x: x[0])
    return scores


def find_relevant_snippets(
    query: str,
    page_texts: List[str],
    k: int = 6,
    # NOTE : `method` est souvent fourni par l'utilisateur (CLI/config) -> on le traite comme `str` à l'exécution.
    # Garder l'union Literal préserve l'autocomplétion pour les valeurs supportées tout en permettant
    # une validation runtime (et évite des faux diagnostics "unreachable code" dans les type checkers).
    method: Literal["count", "count_refine"] | str = "count",
    candidates_k: int = 24,
    min_relative_score: float | None = None,
) -> List[str]:
    """
    Retourne les k meilleurs extraits/pages les plus pertinents pour `query`.

    Arguments :
        query: Chaîne de recherche (souvent des mots-clés).
        page_texts: Liste des textes de pages (un élément par page).
        k: Nombre d'extraits à retourner.
        method:
          - "count": matching lexical en comptant les occurrences (comportement historique).
          - "count_refine": candidates via `count` puis TF‑IDF n‑grams (1-3) avec
            tokenisation souple, et filtrage par score relatif (rel_thr=0.40 par défaut), sans
            seuil absolu TF‑IDF.

    Notes :
        - Toutes les méthodes sont purement lexicales (aucun embedding) et fonctionnent mieux avec
          un texte “propre” (OCR de qualité, moins de césures).
        - Les pages avec un score <= 0 sont exclues.
    """
    if method == "count":
        scores = _count_scores(query, page_texts)
        return [s[2] for s in scores[:k]]

    if method == "count_refine":
        # Candidates via `count`, puis scoring TF‑IDF sur ces candidates, avec filtrage par seuils.
        count_scores = _count_scores(query, page_texts)
        if not count_scores:
            return []

        n = max(k, int(candidates_k))
        candidate_indices = {i for _, i, _ in count_scores[:n]}

        scores = _tfidf_ngram_scores(
            query=query,
            page_texts=page_texts,
            tokenize=_tokenize_soft,
            ngram_range=(1, 3),
            candidate_indices=candidate_indices,
        )
        if not scores:
            return []

        rel_thr = (
            float(VSME_RETRIEVAL_REL_THR)
            if min_relative_score is None
            else float(min_relative_score)
        )
        abs_thr = float(VSME_RETRIEVAL_ABS_THR)
        max_score = float(scores[0][0])
        filtered_rel = (
            [t for t in scores if (float(t[0]) / max_score) >= rel_thr]
            if max_score > 0
            else []
        )
        filtered = [t for t in filtered_rel if float(t[0]) >= abs_thr]
        if not filtered:
            return []
        return [s[2] for s in filtered[:k]]

    raise ValueError(
        f"Méthode inconnue : {method!r}. Attendu : 'count' ou 'count_refine'."
    )


def find_relevant_snippets_with_details(
    query: str,
    page_texts: List[str],
    k: int = 6,
    # NOTE : `method` est souvent fourni par l'utilisateur (CLI/config) -> on le traite comme `str` à l'exécution.
    # Garder l'union Literal préserve l'autocomplétion pour les valeurs supportées tout en permettant
    # une validation runtime (et évite des faux diagnostics "unreachable code" dans les type checkers).
    method: Literal["count", "count_refine"] | str = "count",
    candidates_k: int = 24,
    min_relative_score: float | None = None,
) -> tuple[List[str], dict]:
    """Même retrieval que [`find_relevant_snippets()`](vsme_extractor/retrieval.py:242) mais avec détails de debug.

    Les détails retournés sont conçus pour l'audit / l'analyse dans les sorties JSON.
    """

    details: dict = {
        "method": method,
        "k": int(k),
        "candidates_k": int(candidates_k),
        "query": query,
        "query_tokens": list(dict.fromkeys(_tokenize(query))),
        "thresholds": None,
        "gate": None,
        "pages_candidates": [],
        "pages_kept": [],
        "pages_rejected": [],
        "per_page": [],
    }

    # ------- chemin `count` détaillé (pas de seuils) -------
    if method == "count":
        count_scores = _count_scores(query, page_texts)
        if not count_scores:
            details["gate"] = {"reason": "no_candidates"}
            return [], details

        n = max(k, int(candidates_k))
        candidates = count_scores[:n]
        kept = candidates[:k]

        q_terms = details["query_tokens"]

        details["thresholds"] = None
        details["pages_candidates"] = [int(i) + 1 for _, i, _ in candidates]
        details["pages_kept"] = [int(i) + 1 for _, i, _ in kept]
        details["pages_rejected"] = [int(i) + 1 for _, i, _ in candidates[k:]]

        kept_idx = {i for _, i, _ in kept}
        for score, i, txt in candidates:
            t = (txt or "").lower()
            found_terms = [term for term in q_terms if term and term in t]
            details["per_page"].append(
                {
                    "page": int(i) + 1,
                    "score": int(score),
                    "passed": bool(i in kept_idx),
                    "keywords_found": found_terms,
                    "thresholds": None,
                }
            )

        return [s[2] for s in kept], details

    if method == "count_refine":
        # Candidates via `count`, puis scoring TF‑IDF sur ces candidates, avec filtrage par seuils.
        count_scores = _count_scores(query, page_texts)
        if not count_scores:
            details["gate"] = {"reason": "no_candidates"}
            return [], details

        n = max(k, int(candidates_k))
        candidates_count = count_scores[:n]
        candidate_indices = {i for _, i, _ in candidates_count}

        tfidf_scores = _tfidf_ngram_scores(
            query=query,
            page_texts=page_texts,
            tokenize=_tokenize_soft,
            ngram_range=(1, 3),
            candidate_indices=candidate_indices,
        )
        if not tfidf_scores:
            details["gate"] = {"reason": "no_scores"}
            details["pages_candidates"] = [int(i) + 1 for _, i, _ in candidates_count]
            details["pages_kept"] = []
            details["pages_rejected"] = [int(i) + 1 for _, i, _ in candidates_count]
            return [], details

        rel_thr = (
            float(VSME_RETRIEVAL_REL_THR)
            if min_relative_score is None
            else float(min_relative_score)
        )
        max_score = float(tfidf_scores[0][0])
        abs_thr = float(VSME_RETRIEVAL_ABS_THR)
        thresholds = {
            "rel_thr": float(rel_thr),
            "abs_thr": float(abs_thr),
            "best_score": float(max_score),
        }

        filtered_rel = (
            [t for t in tfidf_scores if (float(t[0]) / max_score) >= rel_thr]
            if max_score > 0
            else []
        )
        filtered = [t for t in filtered_rel if float(t[0]) >= abs_thr]
        kept_tfidf: list[tuple[float, int, str]] = filtered[:k]
        kept_idx = {i for _, i, _ in kept_tfidf}

        tfidf_by_idx: dict[int, float] = {
            i: float(score) for score, i, _ in tfidf_scores
        }
        q_terms = details["query_tokens"]

        details["thresholds"] = thresholds
        details["pages_candidates"] = [int(i) + 1 for _, i, _ in candidates_count]
        details["pages_kept"] = [int(i) + 1 for _, i, _ in kept_tfidf]
        details["pages_rejected"] = [
            int(i) + 1 for _, i, _ in candidates_count if i not in kept_idx
        ]

        for count_score, i, txt in candidates_count:
            t = (txt or "").lower()
            found_terms = [term for term in q_terms if term and term in t]
            tfidf_score = float(tfidf_by_idx.get(i, 0.0))
            tfidf_rel = (tfidf_score / float(max_score)) if max_score > 0 else 0.0
            details["per_page"].append(
                {
                    "page": int(i) + 1,
                    "count_score": int(count_score),
                    "tfidf_score": float(tfidf_score),
                    "tfidf_rel": float(tfidf_rel),
                    "passed": bool(i in kept_idx),
                    "keywords_found": found_terms,
                    "thresholds": thresholds,
                }
            )

        if not kept_tfidf:
            # Soit aucune page ne passe rel_thr, soit certaines passent rel_thr mais sont filtrées par abs_thr.
            details["gate"] = {"reason": "no_page_passed_thresholds"}
            return [], details

        return [s[2] for s in kept_tfidf], details

    raise ValueError(
        f"Méthode inconnue : {method!r}. Attendu : 'count' ou 'count_refine'."
    )

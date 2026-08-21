from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from langchain_community.document_loaders import PyPDFLoader
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def load_pdf(pdf_path: str | Path) -> Tuple[list, List[str], str]:
    """Charge un PDF et retourne (pages, textes_par_page, texte_complet).

    Utilise `PyPDFLoader` (langchain-community) et concatène les pages.
    """
    pdf_path = Path(pdf_path)

    logger.info("START load_pdf | path=%s", pdf_path)

    try:
        # 1) Chemin principal : PyPDFLoader (langchain).
        # Sur certains PDFs "image-only" ou très bruités, PyPDFLoader peut retourner 0 pages.
        loader = PyPDFLoader(str(pdf_path))
        pages = loader.load_and_split()
        page_texts = [p.page_content for p in pages]
        full_text = "\n\n".join(page_texts)

        if len(pages) == 0:
            # 2) Fallback : pypdf pour récupérer au moins le nombre de pages et tenter une extraction.
            # Cela permet de distinguer "PDF sans texte extractible" vs "fichier illisible".
            reader = PdfReader(str(pdf_path))
            page_texts = []
            for page in reader.pages:
                try:
                    page_texts.append(page.extract_text() or "")
                except Exception:
                    page_texts.append("")
            full_text = "\n\n".join(page_texts)
            pages = list(reader.pages)

            logger.warning(
                "PyPDFLoader returned 0 pages -> fallback to pypdf | pages=%s | chars_full_text=%s",
                len(pages),
                len(full_text),
            )

            if len(pages) > 0 and len(full_text.strip()) == 0:
                logger.warning(
                    "PDF has pages but no extractable text (likely scanned/image-only). OCR required for extraction. | path=%s | pages=%s",
                    pdf_path,
                    len(pages),
                )

        logger.info(
            "END load_pdf | pages=%s | chars_full_text=%s",
            len(pages),
            len(full_text),
        )
        return pages, page_texts, full_text
    except Exception:
        logger.exception("FAILED load_pdf | path=%s", pdf_path)
        raise

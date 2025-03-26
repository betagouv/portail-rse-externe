import logging
import os
from pathlib import PosixPath
import functools
import shutil

import fitz
import pandas as pd
import requests
import torch
from beevibe import BeeMLMClassifier, HuggingFaceHub
from celery import shared_task

from flask_app import (
    CURRENT_FULL_PATH,
    MODEL_FILE_PATH,
    PRED_FILE_NAME_JSON,
    REPO_NAME,
    TEXT_FILE_NAME_CSV,
    TEXT_FILE_NAME_PKL,
    init_flask_app,
)
from helpers.extract import ExtractTexts

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
flask_app = init_flask_app()
celery = flask_app.extensions["celery"]


def make_status(document_id: str, status: str, **kwargs) -> dict:
    # harmonise les statuts retournés à l'app (KISS)
    return dict(document_id=document_id, status=status) | kwargs


def notify_app(callback_url: str, status: dict):
    # appelle l'URL de callback avec le statut d'avancement actuel
    
    logger.debug(f"URL de notification : {callback_url}")
    logger.debug(f"contenu de la notification : {status}")

    result = requests.post(callback_url, status)

    logger.debug(f"resultat callback : {result}")
    
    return result


def init_model():
    # initialement chargé avant chaque requête, au final on en a besoin que pour la prédiction
    directory_path = str(CURRENT_FULL_PATH) + "/" + MODEL_FILE_PATH

    if not os.path.exists(directory_path):
        # récupération du jeton HuggingFace
        # Note: plus sûr d'utiliser HF_TOKEN qu'un fichier de configuration
        hf_hub = HuggingFaceHub()
        hf_token = os.getenv("HF_TOKEN")

        hf_hub.load_from_hf_hub(
            directory_path=directory_path,
            repo_name=REPO_NAME,
            token=hf_token,
        )

    model = BeeMLMClassifier.load_model_safetensors(MODEL_FILE_PATH)

    return model


def celery_exception_handler(task_func):
    # si jamais souci pendant le traitement de la tâche
    @functools.wraps(task_func)
    def _inner(*args, **kwargs):
        try:
            return task_func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Erreur dans la tâche Celery {task_func.__name__}: {e}")
            raise

    return _inner


def remove_directory(target):
    # suppression des fichiers de travail
    try:
        shutil.rmtree(target)
        logger.info(f"Répertoire {target} supprimé avec succès.")
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du répertoire {target}: {e}")


def check_pdf_in_path(pdf_key, pdf_path) -> dict:
    PDFs_DIR = PosixPath(pdf_path)
    pdfs = list(PDFs_DIR.glob("*.pdf"))

    if len(pdfs) == 1:
        try:
            doc = fitz.open(pdfs[0])

            if doc.page_count > 0:
                status = "processing"
                msg = "Fichier pdf correct"
            else:
                status = "error"
                msg = "Le fichier .pdf n'est pas un PDF"
        except Exception:
            status = "error"
            msg = "Le fichier .pdf n'est pas un PDF"
    else:
        status = "error"
        msg = "Plusieurs fichiers .pdf trouvés"

    return make_status(
        pdf_key,
        status,
        msg=msg,
    )


def pdf2txt(pdf_key, pdf_path) -> dict:
    pdf_files_dir = PosixPath(pdf_path)
    pdfs = list(pdf_files_dir.glob("*.pdf"))
    pdf = pdfs[0]
    nbtexts = 0
    file_path = str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/"
    pdf_file_path = str(CURRENT_FULL_PATH) + "/" + str(pdf)

    try:
        # Create extractor
        es = ExtractTexts(pdf_file_path)  # , 10, 30)

        # Run extractor
        pd_res = es.process()

        # Filter some texts
        if len(pd_res) > 0:
            # Add indicators
            pd_res.loc[:, "segment_nb_words"] = pd_res.segment_text.apply(
                lambda x: len(x.split())
            )
            pd_res["number_percent"] = pd_res.segment_text.str.count(r"%")
            pd_res["number_rc"] = pd_res.segment_text.str.count(r"\n")
            pd_res["number_tiret"] = pd_res.segment_text.str.count(r"-")
            pd_res["number_count"] = pd_res.segment_text.str.count(r"\d")
            pd_res["char_count"] = pd_res.segment_text.str.replace(
                r"\s+", "", regex=True
            ).str.len()
            pd_res["number_ratio"] = pd_res["number_count"] / pd_res["char_count"]

            # Filtering indicators
            pd_res_filter = pd_res.query(
                "segment_nb_words > 20 and segment_nb_words < 500"
            )
            pd_res_filter = pd_res_filter.query("number_ratio < 0.2")
            pd_res_filter = pd_res_filter.query("number_rc < 10")
            pd_res_filter = pd_res_filter.query("number_percent < 5")
            pd_res_filter = pd_res_filter.query("number_tiret < 6")
            pd_res_filter.segment_text = pd_res_filter.segment_text.str.replace(
                "\xa0", " "
            )
            pd_res_filter = pd_res_filter.loc[:, ["page_num", "segment_text"]]
            pd_res_filter.columns = ["PAGES", "TEXTS"]

            # Save Texts to Pickle and CSV
            pd_res_filter.to_pickle(file_path + TEXT_FILE_NAME_PKL)
            pd_res_filter.to_csv(file_path + TEXT_FILE_NAME_CSV, index=False)

            # Return OK and the number of texts
            nbtexts = pd_res_filter.shape[0]
    except Exception as e:
        msg_utilisateur = "Erreur lors de l’extraction des phrases à analyser"
        msg = f"{msg_utilisateur} : {e}"
        logger.exception(msg)
        return make_status(
            pdf_key,
            "error",
            msg=msg_utilisateur,
        )

    logger.info(f"fin pdf2txt pour {pdf_key}")

    return make_status(
        pdf_key, "text_processed", msg=f"{nbtexts} phrases trouvée(s) dans le PDF"
    )


def esrspredict(pdf_key, pdf_path) -> dict:
    msg = "ESRS analysés avec succès"

    logger.info(f"début d'analyse pour {pdf_key}")

    # Get texts csv file from pdf path
    pkl_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + TEXT_FILE_NAME_PKL
    )
    json_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + PRED_FILE_NAME_JSON
    )

    msg = "Fin d'analyse"

    if os.path.exists(pkl_file_path):
        pd_texts = pd.read_pickle(pkl_file_path)
        raw_texts = pd_texts.TEXTS.values.tolist()

        if len(raw_texts) > 0:
            # TODO: nb de coeurs pour la prediction, à ajuster dynamiquement ? 
            torch.set_num_threads(12)
            model = init_model()

            y_preds = model.predict(raw_texts, batch_size=50, device="cpu")

            texts_esrs = [model.labels_names[k] for k in y_preds]
            pd_texts.loc[:, "ESRS"] = texts_esrs
            pd_texts.groupby("ESRS")[["PAGES", "TEXTS"]].apply(
                lambda x: x.to_dict(orient="records")
            ).to_json(json_file_path)

        else:
            msg = "Aucune phrase n’a été détectée pour l’analyse"

    logger.info(f"fin d'analyse pour ID #{pdf_key}")

    return make_status(pdf_key, status="analysis_complete", msg=msg)


def sendpredsfile(pdf_key, pdf_path) -> dict:
    csv_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + PRED_FILE_NAME_JSON
    )

    with open(csv_file_path) as f:
        content = f.read()

    logger.info(f"fin sendpredsfile pour {pdf_key}")

    return make_status(pdf_key, "success", resultat_json=content)


@shared_task(ignore_result=False)
@celery_exception_handler
def analyser(document_id, pdf_path, callback_url):
    notify_app(callback_url, make_status(document_id, "processing"))

    STEPS = [
        ["vérification du pdf", check_pdf_in_path],
        ["conversion en texte", pdf2txt],
        ["lancement de l'analyse", esrspredict],
        ["envoi des résultats", sendpredsfile],
    ]
    for step_label, function in STEPS:
        logger.info(f"{step_label} : document:{document_id}, path={pdf_path}")
        notification = function(document_id, pdf_path)
        notify_app(callback_url, notification)
        if notification["status"] == "error":
            logger.info(f"erreur, arrêt du traitement pour {document_id}")
            return

    # A ce point, si pas d'erreur, on peut supprimer le dossier de travail
    remove_directory(pdf_path)

    logger.info(f"fin de traitement pour le fichier {document_id} ({pdf_path})")

import logging
import os
from pathlib import PosixPath
import functools

import pandas as pd
import requests
import torch
from beevibe import BeeMLMClassifier, HuggingFaceHub
from celery import shared_task

from flask_app import (
    CURRENT_FULL_PATH,
    MODEL_FILE_PATH,
    PRED_FILE_NAME_CSV,
    REPO_NAME,
    TEXT_FILE_NAME_CSV,
    TEXT_FILE_NAME_PKL,
    APP_BASE_URL,
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


def notify_app(status: dict):
    # appelle l'URL de callbach avec le statut d'avancewment actuel
    callback_url = f"{APP_BASE_URL}/ESRS-predict/{status['document_id']}"
    requests.post(callback_url, status)


def init_model():
    # initialement chargé avant chaque requête, au final on en a besoin que pour la prédiction
    directory_path = str(CURRENT_FULL_PATH) + "/" + MODEL_FILE_PATH

    if not os.path.exists(directory_path):
        # Get HuggingFace token
        # Note: getting out the token from a versionned file using and HF_TOKEN env-var instead
        hf_hub = HuggingFaceHub()
        hf_token = os.getenv("HF_TOKEN")

        # Download model from hub
        hf_hub.load_from_hf_hub(
            directory_path=directory_path, repo_name=REPO_NAME, token=hf_token
        )

    # Load Model in memory
    model = BeeMLMClassifier.load_model_safetensors(MODEL_FILE_PATH)

    # Add model to the list (only 1 model here)
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


def pdf2txt(pdf_key, pdf_path) -> dict:
    # Paths to PDF file
    PDFs_DIR = PosixPath(pdf_path)
    pdfs = list(PDFs_DIR.glob("*.pdf"))
    pdf = pdfs[0]
    nbtexts = 0

    # Path to texts files
    file_path = str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/"

    # Path to the token directory
    PDF_FILE_PATH = str(CURRENT_FULL_PATH) + "/" + str(pdf)

    try:
        # Create extractor
        es = ExtractTexts(PDF_FILE_PATH)  # , 10, 30)

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
        msg = f"erreur de traitement lors du passage de PDF a TXT : {e}"
        logger.exception(msg)
        return make_status(
            pdf_key,
            "error",
            msg=msg,
        )

    logger.info(f"fin pdf2txt pour {pdf_key}")

    return make_status(
        pdf_key, "text_processed", msg=f"{nbtexts} trouvé(s) dans le PDF"
    )


def esrspredict(pdf_key, pdf_path) -> dict:
    msg = "ESRS analysés avec succès"

    logger.info(f"début d'analyse pour {pdf_key}")

    # Get texts csv file from pdf path
    pkl_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + TEXT_FILE_NAME_PKL
    )
    csv_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + PRED_FILE_NAME_CSV
    )

    msg = pkl_file_path

    # Check if texts file exist
    if os.path.exists(pkl_file_path):
        # Open texts file
        pd_texts = pd.read_pickle(pkl_file_path)
        raw_texts = pd_texts.TEXTS.values.tolist()

        # Predict ESRS
        if len(raw_texts) > 0:
            # Set nb cores for multi-threading
            torch.set_num_threads(12)

            # Get model
            # model = MODELS[0]
            model = init_model()

            # Predict ESRS
            y_preds = model.predict(raw_texts, batch_size=50, device="cpu")

            # Save predictions to CSV file
            texts_esrs = [model.labels_names[k] for k in y_preds]
            pd_texts.loc[:, "ESRS"] = texts_esrs
            pd_texts.to_csv(csv_file_path, index=False)

        else:
            msg = "Pas de texte à analyser"

    logger.info(f"fin d'analyse pour {pdf_key}")

    return make_status(pdf_key, status="analysis_complete", msg=msg)


def sendpredsfile(pdf_key, pdf_path) -> dict:
    csv_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + PRED_FILE_NAME_CSV
    )

    with open(csv_file_path) as f:
        content = f.read()

    logger.info(f"fin sendpredsfile pour {pdf_key}")

    # TODO : JSON
    return make_status(pdf_key, "success", resultat_csv=content)


@shared_task(ignore_result=False)
@celery_exception_handler
def analyser(document_id, pdf_path):
    notify_app(make_status(document_id, "processing"))

    logger.info(f"conversion en texte : document:{document_id}, path={pdf_path}")
    notify_app(pdf2txt(document_id, pdf_path))

    logger.info(f"lancement de l'analyse : document:{document_id}, path={pdf_path}")
    notify_app(esrspredict(document_id, pdf_path))

    logger.info(f"envoi des résultats : document:{document_id}, path={pdf_path}")
    notify_app(sendpredsfile(document_id, pdf_path))

    logger.info(f"fin de traitement pour le fichier {document_id} ({pdf_path})")

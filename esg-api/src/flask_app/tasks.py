import logging
import os
from pathlib import PosixPath

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
    init_flask_app,
)
from helpers.extract import ExtractTexts

flask_app = init_flask_app()
celery = flask_app.extensions["celery"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL")


def init_model():
    # initialement chargé avant chaque requête, au final on en a besoin que pour la prédiction
    directory_path = str(CURRENT_FULL_PATH) + "/" + MODEL_FILE_PATH

    if not os.path.exists(directory_path):
        # Get HuggingFace token
        # Note: getting out the token from a versionned file and using HF_TOKEN env-var instead
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


@shared_task(ignore_result=False)
def analyser(document_id, pdf_path):
    url = f"{APP_BASE_URL}/ESRS-predict/{document_id}"
    requests.post(url, {"status": "analyse en cours"})

    pdf2txt(document_id, pdf_path)
    esrspredict(document_id, pdf_path)
    sendpredsfile(document_id, pdf_path)

def pdf2txt(pdf_key, pdf_path):
    # Paths to PDF file
    PDFs_DIR = PosixPath(pdf_path)
    pdfs = list(PDFs_DIR.glob("*.pdf"))
    pdf = pdfs[0]

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
            status_dict = {"code": 1, "msg": f"{nbtexts} texts found in PDF"}
        else:
            nbtexts = 0
            status_dict = {"code": -2, "msg": "No text found in PDF"}

    except Exception as e:
        nbtexts = 0
        status_dict = {"code": -1, "msg": f"Can't convert PDF to TXT {e}"}

    logger.info(f"fin pdf2txt pour {pdf_key} : {status_dict}")

def esrspredict(pdf_key, pdf_path):
    status_dict = {"code": 0, "msg": "ESRS predicted with success"}

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
            status_dict = {"code": -2, "msg": "No texts to predict"}
    else:
        status_dict = {"code": -1, "msg": msg}  # "Texts must be generated"}

    logger.info(f"fin d'analyse pour {pdf_key} : {status_dict}")


def sendpredsfile(pdf_key, pdf_path):
    csv_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + PRED_FILE_NAME_CSV
    )
    with open(csv_file_path) as f:
        content = f.read()
    url = f"{APP_BASE_URL}/ESRS-predict/{pdf_key}"
    requests.post(url, {"status": "success", "resultat_csv": content})

    logger.info(f"fin sendpredsfile pour {pdf_key}")

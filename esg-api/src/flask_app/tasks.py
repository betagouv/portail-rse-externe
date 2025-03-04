import logging
import os

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
    TEXT_FILE_NAME_PKL,
    init_flask_app,
)

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

    url = f"{APP_BASE_URL}/ESRS-predict/{pdf_key}"
    requests.get(url, {"status": "analyse en cours"})

"""
Created on 2024-08-01 00:00:00

This module provides functions and classes to detect each ESRS sentences in a French report via API.
The machine learning component used is a Transformer classifier trained on a custom dataset.

@author: fbullier@360client.fr
@maintainer: fbullier@360client.fr

MEF/360Client
"""

import logging
import os

import requests
from flask import abort, request, jsonify
from flask_jwt_extended import JWTManager, jwt_required
from flasgger import Swagger

import flask_app.tasks as tasks

# voir :__init__.py
from flask_app import (
    FLASK_ENV,
    WS_PATH,
    init_flask_app,
)


# Flask components
app = init_flask_app()
if FLASK_ENV != "production":
    swagger = Swagger(app)
jwt = JWTManager(app)
logger = logging.getLogger(__name__)


def _fetch_s3_document(url: str, document_id: str) -> str:
    response = requests.get(url)
    pdf_path = f"{WS_PATH}/document_{document_id}"
    file_path = f"{pdf_path}/fichier.pdf"

    os.makedirs(pdf_path, exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(response.content)

    return pdf_path


@app.route("/ping", methods=["GET"])
def ping():
    """
    Vérifie si le serveur est en fonctionnement
    ---
    responses:
      200:
        description: Le serveur est en fonctionnement
    """
    return jsonify({"status": "alive", "msg": "API is alive and well"})


@app.route("/run-task", methods=["POST"])
@jwt_required(skip_revocation_check=True, verify_type=False)
def run_task():
    """
    Exécute une tâche
    ---
    parameters:
      - name: document_id
        in: formData
        type: string
        required: true
        description: L'ID du document
      - name: document_url
        in: formData
        type: string
        required: true
        description: L'URL du document
      - name: callback_url
        in: formData
        type: string
        required: true
        description: L'URL de rappel
    responses:
      200:
        description: La tâche a été démarrée avec succès
      400:
        description: Données de tâche invalides
    """
    logger.info("params:", request.form)
    try:
        document_id = request.form["document_id"]
        s3_url = request.form["document_url"]
        callback_url = request.form["callback_url"]
        pdf_path = _fetch_s3_document(s3_url, document_id)
    except Exception as ex:
        logger.exception(ex)
        return jsonify({"status": "error", "msg": str(ex)})
    else:
        # à ce point, les erreurs sont gérées par la tâche Celery
        tasks.analyser.delay(document_id, pdf_path, callback_url)

        return jsonify({"status": "pending"})

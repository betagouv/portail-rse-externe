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
from flask import request, jsonify
from flask_jwt_extended import JWTManager, jwt_required

import flask_app.tasks as tasks

# voir :__init__.py
from flask_app import (
    WS_PATH,
    init_flask_app,
)

# Flask components
app = init_flask_app()
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
    return jsonify({"status": "alive", "msg": "API is alive and well"})


@app.route("/run-task", methods=["POST"])
@jwt_required()
def run_task():
    logger.info("params:", request.form)
    try:
        document_id = request.form["document_id"]
        s3_url = request.form["url"]
        pdf_path = _fetch_s3_document(s3_url, document_id)
    except Exception as ex:
        logger.exception(ex)
        return jsonify({"status": "error", "msg": str(ex)})
    else:
        # à ce point, les erreurs sont gérées par la tâche Celery
        tasks.analyser.delay(document_id, pdf_path)

        return jsonify({"status": "en attente"})

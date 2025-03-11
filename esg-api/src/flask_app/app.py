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
from functools import wraps
from pathlib import PosixPath

import fitz
import requests
from flask import abort, json, make_response, request, send_file
from flask_jwt_extended import JWTManager, jwt_required

import flask_app.tasks as tasks

# voir :__init__.py
from flask_app import (
    CURRENT_FULL_PATH,
    TEXT_FILE_NAME_CSV,
    WS_PATH,
    init_flask_app,
)

# Flask components
app = init_flask_app()
jwt = JWTManager(app)
logger = logging.getLogger(__name__)


# jsonify API responses
def json_response(msg_dict, status=200, indent=4, sort_keys=True):
    response = make_response(
        json.dumps(msg_dict, ensure_ascii=False, indent=indent, sort_keys=sort_keys)
    )
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["mimetype"] = "application/json"
    response.status_code = status
    return response


# Delete all pdfs from workspace
def deltree(target):
    for d in os.listdir(target):
        try:
            deltree(target + "/" + d)
        except OSError:
            os.remove(target + "/" + d)
    os.rmdir(target)


# Check if a file is a pdf
def check_pdf_in_path(pdf_path):
    PDFs_DIR = PosixPath(pdf_path)
    pdfs = list(PDFs_DIR.glob("*.pdf"))

    if len(pdfs) == 1:
        # Check .pdf File is not a PDF
        try:
            # Attempt to open the file
            doc = fitz.open(pdfs[0])

            # Check the PDF page count
            if doc.page_count > 0:
                return 0
            else:
                return -1
        except Exception:
            return -1
    else:
        # Too many .pdf files found
        return -3


# Check if pdf token is given
def pdf_token_required(f):
    @wraps(f)
    def decorator(*args, **kwargs):
        if request.method == "POST":
            pdf_key = request.form.get("pdfkey")
        else:
            pdf_key = request.args.get("pdfkey")

        # Check if a pdf_key is given
        if pdf_key is None:
            status_dict = {"code": -1, "msg": "PDF key is empty"}
            resp_dict = {"status": status_dict}
            return json_response(resp_dict)
        else:
            # Path to pdf file
            pdf_path = WS_PATH + "/" + "pdf_" + pdf_key

            # Check if pdf_key path exists
            if os.path.exists(pdf_path):
                # Check if the uploaded file is a pdf
                ret = check_pdf_in_path(pdf_path)

                if ret == -1:
                    status_dict = {"code": -1, "msg": ".pdf file is not a PDF file"}
                    resp_dict = {"status": status_dict}
                    return json_response(resp_dict)

                elif ret == -2:
                    status_dict = {"code": -1, "msg": "No .pdf file found"}
                    resp_dict = {"status": status_dict}
                    return json_response(resp_dict)

                elif ret == -3:
                    status_dict = {"code": -1, "msg": "Too many .pdf files found"}
                    resp_dict = {"status": status_dict}
                    return json_response(resp_dict)

                else:
                    return f(pdf_key, pdf_path, *args, **kwargs)

            else:
                status_dict = {"code": -1, "msg": "PDF key not found"}
                resp_dict = {"status": status_dict}
                return json_response(resp_dict)

    return decorator


@app.errorhandler(400)
def page_not_found(_):
    return "bad request!", 400


@app.route("/")
def index():
    status_dict = {"code": 0, "msg": "Welcome to the ESRS API"}
    resp_dict = {"status": status_dict}
    return json_response(resp_dict)


@app.route("/ping", methods=["GET", "POST"])
def ping():
    status_dict = {"code": 0, "msg": "API is alive"}
    resp_dict = {"status": status_dict}
    return json_response(resp_dict)


# TODO: pas convaincu de l'intérêt de cette route
# le nettoyage pourrait être effectué à chaque succés
@app.route("/clean", methods=["GET", "POST"])
@pdf_token_required
@jwt_required()
def clean(pdf_key, pdf_path):
    status_dict = {"code": 0, "msg": "Cleaning done"}
    resp_dict = {"status": status_dict}

    # Delete pdf_key directory
    deltree(pdf_path)

    return json_response(resp_dict)


# TODO: pas convaincu de l'intérêt de cette route
@app.route("/gettxtfile", methods=["GET", "POST"])
@pdf_token_required
@jwt_required()
def gettxtfile(pdf_key, pdf_path):
    # Get texts csv file from pdf path
    text_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + TEXT_FILE_NAME_CSV
    )

    try:
        return send_file(text_file_path, as_attachment=True)

    except FileNotFoundError:
        abort(404)


# Note: que se passe t'il si une prédiction est en cours ?
@app.route("/cleanall", methods=["GET", "POST"])
@jwt_required()
def clean_all():
    # Delete bert directory and temporary files
    if os.path.exists(WS_PATH):
        deltree(WS_PATH)

    # Create an empty workspace
    os.makedirs(WS_PATH)

    status_dict = {"code": 0, "msg": "Cleaning done"}
    resp_dict = {"status": status_dict}
    return json_response(resp_dict)


@app.route("/run-task", methods=["POST"])
@jwt_required()
def run_task():
    logger.info("params:", request.form)
    try:
        document_id = request.form["document_id"]
        s3_url = request.form["url"]
        response = requests.get(s3_url)
        pdf_path = f"{WS_PATH}/document_{document_id}"
        os.makedirs(pdf_path, exist_ok=True)
        file_path = f"{pdf_path}/fichier.pdf"

        with open(file_path, "wb") as f:
            f.write(response.content)
    except Exception as ex:
        logger.exception(ex)
        return json_response({"status": "error", "msg": str(ex)})
    else:
        # à ce point, les erreurs sont gérées par la tâche Celery
        tasks.analyser.delay(document_id, pdf_path)

        return json_response({"status": "en attente"})

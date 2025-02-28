"""
Created on 2024-08-01 00:00:00

This module provides functions and classes to detect each ESRS sentences in a French report via API.
The machine learning component used is a Transformer classifier trained on a custom dataset.

@author: fbullier@360client.fr
@maintainer: fbullier@360client.fr

MEF/360Client
"""

import os
import tempfile
from functools import wraps
from pathlib import PosixPath

import fitz
import pandas as pd
import torch
from beevibe import BeeMLMClassifier, HuggingFaceHub
from flask import Flask, abort, json, make_response, request, send_file
from werkzeug.utils import secure_filename

# Import custom packages
from helpers.extract import ExtractTexts

# Current full path and xpdf path
CURRENT_FULL_PATH = os.getcwd()

# File names
TEXT_FILE_NAME_PKL = "texts_file.pkl"
TEXT_FILE_NAME_CSV = "texts_file.csv"
PRED_FILE_NAME_CSV = "esrs_preds.csv"

# HuggingFace model name and repo name
MODEL_NAME = "distill-camembert-esrs-v1"
REPO_NAME = "Franbul/" + MODEL_NAME

# Workspace directory
WS_PATH = "./workspace"
os.makedirs(WS_PATH, exist_ok=True)

# Load trained model
MODEL_PATH = "./models/"
MODEL_FILE_PATH = MODEL_PATH + MODEL_NAME
CURRENT_DEVICE = "cpu"
MODELS = []

# Flask API
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # < 100 MB


@app.before_request
def load_model():
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
    MODELS.append(model)


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


@app.route("/clean", methods=["GET", "POST"])
@pdf_token_required
def clean(pdf_key, pdf_path):
    status_dict = {"code": 0, "msg": "Cleaning done"}
    resp_dict = {"status": status_dict}

    # Delete pdf_key directory
    deltree(pdf_path)

    return json_response(resp_dict)


@app.route("/pdf2txt", methods=["GET", "POST"])
@pdf_token_required
def pdf2txt(pdf_key, pdf_path):
    status_dict = {"code": 0, "msg": "PDF is converted to TXT"}

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

        else:
            nbtexts = 0
            status_dict = {"code": -2, "msg": "No text found in PDF"}

    except Exception:
        nbtexts = 0
        status_dict = {"code": -1, "msg": "Can't convert PDF to TXT"}
        pass

    resp_dict = {"status": status_dict, "nbtexts": nbtexts}
    return json_response(resp_dict)


@app.route("/gettxtfile", methods=["GET", "POST"])
@pdf_token_required
def gettxtfile(pdf_key, pdf_path):
    # Get texts csv file from pdf path
    text_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + TEXT_FILE_NAME_CSV
    )

    try:
        return send_file(text_file_path, as_attachment=True)

    except FileNotFoundError:
        abort(404)


@app.route("/esrspredict", methods=["GET", "POST"])
@pdf_token_required
def esrspredict(pdf_key, pdf_path):
    status_dict = {"code": 0, "msg": "ESRS predicted with success"}

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
            model = MODELS[0]

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

    resp_dict = {"status": status_dict}
    return json_response(resp_dict)


@app.route("/getpredsfile", methods=["GET", "POST"])
@pdf_token_required
def getpredsfile(pdf_key, pdf_path):
    # Get texts csv file from pdf path
    csv_file_path = (
        str(CURRENT_FULL_PATH) + "/" + str(pdf_path) + "/" + PRED_FILE_NAME_CSV
    )

    try:
        return send_file(csv_file_path, as_attachment=True)

    except FileNotFoundError:
        abort(404)


@app.route("/cleanall", methods=["GET", "POST"])
def clean_all():
    # Delete bert directory and temporary files
    if os.path.exists(WS_PATH):
        deltree(WS_PATH)

    # Create an empty workspace
    os.makedirs(WS_PATH)

    status_dict = {"code": 0, "msg": "Cleaning done"}
    resp_dict = {"status": status_dict}
    return json_response(resp_dict)


@app.route("/upload", methods=["POST"])
def upload():
    # Create a key directory for th pdf file
    pdf_key = tempfile.mkdtemp(prefix="").split("/")[2]
    pdf_path = WS_PATH + "/" + "pdf_" + pdf_key

    # Default return status
    status_dict = {"code": 0, "msg": "PDF is uploaded"}
    resp_dict = {"status": status_dict, "pdfkey": pdf_key}

    # Get uploaded file
    uploaded_file = request.files["file"]

    # Secured file name
    filename = secure_filename(os.path.basename(uploaded_file.filename))

    # file extension
    file_ext = os.path.splitext(filename)[1]

    # Check if file name exists
    if filename != "":
        if file_ext in [".pdf"]:
            if not os.path.exists(pdf_path):
                os.makedirs(pdf_path)

            # Save pdf file
            uploaded_file.save(pdf_path + "/" + filename)

        else:
            status_dict = {"code": -1, "msg": "extension must be .pdf"}
            resp_dict = {"status": status_dict, "file_ext": file_ext}

    else:
        status_dict = {"code": -1, "msg": "File name is missing"}
        resp_dict = {"status": status_dict}

    return json_response(resp_dict)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=43440)

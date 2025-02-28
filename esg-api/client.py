import io
import time as time
import pandas as pd
import requests

import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

API_URL = "http://127.0.0.1:5000"


def api_status():
    url = f"{API_URL}/ping"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data
    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def post_pdf(pdf_path):
    """etape 1 du traitement"""
    try:
        t0 = time.time()
        url = f"{API_URL}/upload"

        mp = {"file": (pdf_path, open(pdf_path, "rb"), "multipart/form-data")}
        response = requests.post(url, files=mp, verify=False)

        resp_dict = response.json()
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print("1", errh)
    except requests.exceptions.ConnectionError as errc:
        print("2", errc)
    except requests.exceptions.Timeout as errt:
        print("3", errt)
    except requests.exceptions.RequestException as err:
        print("4", err)


def convert_pdf_to_text(pdf_key):
    """etape 2 du traitement"""
    url = f"{API_URL}/pdf2txt?pdfkey={pdf_key}"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def predict_esrs_from_texts(pdf_key):
    """etape 3 du traitement"""
    url = f"{API_URL}/esrspredict?pdfkey={pdf_key}"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def check_activity(pdf_key):
    url = f"{API_URL}/checkactivetask?pdfkey={pdf_key}"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def count_tasks():
    url = f"{API_URL}/getnbactivetasks"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def get_texts(pdf_key):
    """etape 4 du traitement"""
    url = f"{API_URL}/gettxtfile?pdfkey={pdf_key}"
    texts_pd_key = {}

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = io.StringIO(str(response.content, "utf-8"))
        texts_pd_key[pdf_key] = pd.read_csv(data)
        data = {}
        data["nb texts"] = len(texts_pd_key[pdf_key])
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def get_predictions(pdf_key):
    """etape 5 du traitement"""
    df_pdf_key = pd.DataFrame([])

    url = f"{API_URL}/getpredsfile?pdfkey={pdf_key}"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        content = io.StringIO(str(response.content, "utf-8"))
        df = pd.read_csv(content)
        data = {
            "content": df,
            "status_code": response.status_code,
            "elapsed_time": round(time.time() - t0),
        }
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


def clean_pdf(pdf_key):
    """nettoyage post-traitement"""
    url = f"{API_URL}/clean?pdfkey={pdf_key}"

    try:
        t0 = time.time()
        response = requests.get(url, verify=False)
        data = response.json()
        data["status_code"] = response.status_code
        data["elapsed_time"] = round(time.time() - t0)
        return data

    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)

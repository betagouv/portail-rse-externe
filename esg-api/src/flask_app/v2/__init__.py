import logging

from flask_app.v1 import make_status
from flask_app.v1 import notify_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def analyser(document_id, pdf_path, callback_url):
    notify_app(callback_url, make_status(document_id, "processing v2"))

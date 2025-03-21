import os
from celery import Celery, Task
import logging
from flask import Flask


# Current full path and xpdf path
CURRENT_FULL_PATH = os.getcwd()

# File names
TEXT_FILE_NAME_PKL = "texts_file.pkl"
TEXT_FILE_NAME_CSV = "texts_file.csv"
PRED_FILE_NAME_JSON = "esrs_preds.json"

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

# Endpoint de l'application Portail RSE
APP_BASE_URL = os.getenv("APP_BASE_URL")

# Pour la gestion des tokens JWT
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

# Flask & Celery
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # < 100 MB
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

logger = logging.getLogger(__name__)


def init_celery_app(flask_app: Flask) -> Celery:
    class _Task(Task):
        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(
        flask_app.name,
        task_cls=_Task,
        backend=CELERY_RESULT_BACKEND,
        broker=CELERY_BROKER_URL,
        broker_connection_retry_on_startup=True,
    )

    celery_app.set_default()
    flask_app.extensions["celery"] = celery_app

    return celery_app


def init_flask_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    flask_app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
    ...

    init_celery_app(flask_app)

    return flask_app

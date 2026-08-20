import logging
import functools

from celery import shared_task

from flask_app.v1 import analyser as analyser_v1
from flask_app.v2 import analyser as analyser_v2

logger = logging.getLogger(__name__)

from flask_app import (
    init_flask_app,
 )
flask_app = init_flask_app()
celery = flask_app.extensions["celery"]


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


@shared_task(ignore_result=False)
@celery_exception_handler
def analyser(document_id, pdf_path, callback_url, ai_version):
    if ai_version == "1":
        analyser_v1(document_id, pdf_path, callback_url)
    else:
        analyser_v2(document_id, pdf_path, callback_url)


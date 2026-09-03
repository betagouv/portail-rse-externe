import logging

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def make_status(document_id: str, status: str, **kwargs) -> dict:
    # harmonise les statuts retournés à l'app (KISS)
    return dict(document_id=document_id, status=status) | kwargs


def notify_app(callback_url: str, status: dict):
    # appelle l'URL de callback avec le statut d'avancement actuel

    logger.info(f"URL de notification : {callback_url}")
    logger.info(f"contenu de la notification : {status}")

    result = requests.post(callback_url, status)

    logger.info(f"resultat callback : {result}")

    return result

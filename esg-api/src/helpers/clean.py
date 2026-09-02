import logging
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def remove_directory(target):
    # suppression des fichiers de travail
    try:
        shutil.rmtree(target)
        logger.info(f"Répertoire {target} supprimé avec succès.")
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du répertoire {target}: {e}")

# Portail RSE - app externes

Ce dépôt contient les sources des projets et apps externes pour le [Portail RSE](https://github.com/betagouv/portail-rse).


## Note

Il est probable qu'il ne soit qu'un espace de travail temporaire pour être ensuite réintégré vers le dépôt principal du projet (_mono-repo_).


## Développement local

### Créer le virtualenv

```
cd esg-api
uv sync
```

### Installer Taskfile 

Voir : [Taskfile](https://taskfile.dev) :

### Environnement

Modifier et copier `example.env` dans `esg-api/.env`

Paramétrer les variables suivantes :
- `HF_TOKEN` : token d'accès au dépôt du modèle de prédiction sur HuggingFace
- `CELERY_BROKER_URL` : endpoint du broker Celery (par défaut : instance Redis locale)
- `CELERY_RESULT_BACKEND` : endpoint pour les tâches Celery (par défaut : instance Redis locale)
- `PYTHONPATH` : inclure le dossier `src` comme indiqué dans le fichier d'exemple pour modifier le chemin système de Python
- `APP_BASE_URL` : le domaine de l'app django (préfixé par le protocole)


### Exécuter Flask

``` 
task flask
``` 

### Exécuter Flask et les workers Celery 

Execute à la fois les commandes de lancement des workers Celery et de l'application Flask via Honcho. 
```
task dev
```

### Utiliser le notebook

```
jupyter notebook esg-api/notebook/detect_api_in_jupyter.ipynb
```

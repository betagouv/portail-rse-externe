# Portail RSE - app externes

Ce dépôt contient les sources des projets et apps externes pour le [Portail RSE](https://github.com/betagouv/portail-rse).


## Note

Il est probable qu'il ne soit qu'un espace de travail temporaire pour être ensuite réintégré vers le dépôt principal du projet (_mono-repo_).


## Développement local

### Créer le virtualenv

```
python3 -m venv venv
. ./venv/bin/activate
pip install -r esg-api/app/requirements.txt
pip install requests #pour jupyter
```

### Modifier config.ini

Sert à paramétrer `token`

### Exécuter flask

```
cd esg-api/app
flask run
```

### Utiliser le notebook

```
jupyter notebook esg-api/notebook/detect_api_in_jupyter.ipynb
```
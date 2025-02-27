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

### Environnement

Copier `example.env` dans `esg-api/app/.env`
Paramétrer `HF_TOKEN`

### Exécuter flask

```
uv run -- flask --app app.app run
```

### Utiliser le notebook

```
jupyter notebook esg-api/notebook/detect_api_in_jupyter.ipynb
```
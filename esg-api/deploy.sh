#!/bin/bash
set -e

echo "🚀 Début du script de déploiement"

echo "🔄 Mise à jour du code depuis Github"
git checkout main
git pull origin main

echo "🛑 Arrêt de l'ancien conteneur"
podman-compose down

echo "🧱 Reconstruction de l'image et lancement du nouveau conteneur"
podman-compose up --build --remove-orphans -d 

echo "🧹 Nettoyage des anciennes images"
podman image prune -f

echo "🎉 Fin du script de déploiement"

exit 0

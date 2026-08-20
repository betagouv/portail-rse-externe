# 🚀 ESG-API

TODO : compléter la documentation

## Déploiement d'une nouvelle version de l'API

Cette procédure est probablement temporaire, mais fonctionnelle :
- les nouveaux déploiements d'API ne sont pas fréquents,
- par raison de sécurité, les déploiements ne sont pas automatiques (par ex. sur écoute Github), mais nécessitennt une intervention *manuelle*.

### Détail de la procédure de déploiement

- se connecter en `ssh` au serveur (seuls les devs ont des comptes actuellement) : ` ssh nom_utilisateur@ia.portail-rse.beta.gouv.fr`
- passer en utilisateur `podman`: `sudo -s -u podman`
- se placer dans le répertoire de l'app : `cd /home/podman/portail-rse-externe/esg-api/`
- lancer le script de déploiement : `./deploy.sh`
- se déconnecter
- *done*

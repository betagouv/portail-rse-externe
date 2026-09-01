# 🚀 ESG-API

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

En production, les variables d'environnement sont dans le fichier `/home/podman/portail-rse-externe/esg-api/.env`.


## Voir, redémarrer les conteneurs Podman


Se connecter en ssh sur la machine puis :

```
sudo -i -u podman
podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml stop # arreter les 3 processus
podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml ps # vérifier l'état
podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml start
```

```
[podman@portail-rse-ia ~]$ podman ps -a
CONTAINER ID  IMAGE                           COMMAND               CREATED        STATUS        PORTS                                                                         NAMES
24392598889e  docker.io/library/redis:latest  redis-server          16 months ago  Up 16 months  6379/tcp                                                                      redis
d64e4b788dbe  localhost/esg-api_flask:latest  uv run honcho sta...  16 months ago  Up 16 months  5000/tcp                                                                      esg-api_flask_1
3af9b8efb18a  docker.io/library/caddy:latest  caddy run --confi...  16 months ago  Up 16 months  0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp, 80/tcp, 443/tcp, 443/udp, 2019/tcp  caddy
[podman@portail-rse-ia ~]$ podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml stop
caddy
redis
esg-api_flask_1
[podman@portail-rse-ia ~]$ podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml ps
CONTAINER ID  IMAGE                           COMMAND               CREATED        STATUS                      PORTS                                                                         NAMES
24392598889e  docker.io/library/redis:latest  redis-server          16 months ago  Exited (0) 4 seconds ago    6379/tcp                                                                      redis
d64e4b788dbe  localhost/esg-api_flask:latest  uv run honcho sta...  16 months ago  Exited (143) 3 seconds ago  5000/tcp                                                                      esg-api_flask_1
3af9b8efb18a  docker.io/library/caddy:latest  caddy run --confi...  16 months ago  Exited (0) 4 seconds ago    0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp, 80/tcp, 443/tcp, 443/udp, 2019/tcp  caddy
[podman@portail-rse-ia ~]$ podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml start
redis
esg-api_flask_1
caddy
[podman@portail-rse-ia ~]$ podman-compose -f ~/portail-rse-externe/esg-api/docker-compose.yml ps
CONTAINER ID  IMAGE                           COMMAND               CREATED        STATUS        PORTS                                                                         NAMES
24392598889e  docker.io/library/redis:latest  redis-server          16 months ago  Up 3 seconds  6379/tcp                                                                      redis
d64e4b788dbe  localhost/esg-api_flask:latest  uv run honcho sta...  16 months ago  Up 3 seconds  5000/tcp                                                                      esg-api_flask_1
3af9b8efb18a  docker.io/library/caddy:latest  caddy run --confi...  16 months ago  Up 3 seconds  0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp, 80/tcp, 443/tcp, 443/udp, 2019/tcp  caddy
```

Il est possible de voir les logs d'un conteneur avec `podman logs id_du_conteneur`.

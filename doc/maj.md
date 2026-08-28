# Etapes

- savoir redémarrer le service (cf. podman.md)
- redémarrer la machine (`sudo systemctl reboot`) pour vérifier son bon fonctionnement avant la maj
- maj système (`dnf upgrade -y`) cf. https://wiki.almalinux.org/release-notes/9.8.html#upgrade-instructions
- redémarrer la machine (`sudo systemctl reboot`) pour être sûr de sa prise en compte totale
- maj des images `podman` avec `deploy.sh` (cf. deploiement.md)
- vérifier le bon fonctionnement du service

Cette documentation est issue de https://github.com/betagouv/portail-rse/issues/977

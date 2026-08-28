# Création d'un service Podman pour le serveur IA

Pour créer proprement un utilisateur dédié `podman` qui gérera le service, voici la procédure complète :

1. Créer l'utilisateur `podman` :

```bash
sudo useradd -m -s /bin/bash podman
```

2. Configurer le *lingering* pour cet utilisateur afin que ses services `systemd` puissent s'exécuter même s'il n'est pas connecté :

```bash
sudo loginctl enable-linger podman
```

3. Configurer des limites système appropriées pour l'utilisateur `podman` :

```bash
sudo tee -a /etc/security/limits.d/podman.conf << EOF
podman soft nofile 65536
podman hard nofile 65536
podman soft nproc 4096
podman hard nproc 4096
EOF
```

4. Passer à l'utilisateur `podman` :

```bash
sudo -i -u podman
```

5. Vérifier que Podman fonctionne pour cet utilisateur :

```bash
podman info
```

6. Créer le répertoire pour les fichiers `docker-compose` :

```bash
mkdir -p ~/docker-compose-services/podman
```

7. Copier le `docker-compose.yml` dans ce répertoire :

```bash
# Depuis votre session utilisateur podman
# Remplacez le chemin par celui de votre fichier
cp /chemin/vers/votre/docker-compose.yml ~/docker-compose-services/podman/
```

8. Configurer le service `systemd` au niveau utilisateur :

```bash
mkdir -p ~/.config/systemd/user/
```

9. Quitter la session de l'utilisateur `podman` :

```bash
exit
```

Si vous avez besoin d'accorder des privilèges supplémentaires à l'utilisateur `podman` (comme l'accès à certains ports privilégiés), vous pouvez configurer les capacités nécessaires via des paramètres système :

```bash
# Autoriser la liaison à des ports < 1024 sans privilèges root
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
```

Pour rendre ce paramètre permanent, ajoutez-le à `/etc/sysctl.conf` :

```bash
sudo echo "net.ipv4.ip_unprivileged_port_start=80" >> /etc/sysctl.conf
```


Cette documentation est issue de https://github.com/betagouv/portail-rse/discussions/425

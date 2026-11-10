# dso-secrets

Package Python pour lire et écrire des secrets dans OVHcloud OKMS (Secret Manager), ou lire une copie locale hors ligne.

## Installation

```bash
pip install "git+https://github.com/dso-conseils/dso-secrets.git@v0.3.2"
```

## Configuration

La configuration est un fichier YAML situé à un emplacement unique : `~/.dso-secrets/config.yml` (sous Windows : `%USERPROFILE%\.dso-secrets\config.yml`).

Pour le créer, lancer :

```bash
dso-secrets init
```

La commande pose les questions une par une et écrit le fichier. Options : `--mode local` (mode hors ligne), `--output <fichier>` (autre emplacement), `--force` (remplacer un fichier existant).

Le YAML ne contient jamais de secret : une clé du type `client_secret`, `password` ou `token` est refusée.

Pour un container ou une CI, le contenu du YAML peut être fourni dans la variable d'environnement `DSO_SECRETS_CONFIG_YAML`, ou le fichier monté à l'emplacement ci-dessus.

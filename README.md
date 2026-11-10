# dso-secrets

Package Python pour lire et Ã©crire des secrets dans OVHcloud OKMS (Secret Manager), ou lire une copie locale hors ligne.

## Installation

```bash
pip install "git+https://github.com/dso-conseils/dso-secrets.git@v0.3.0"
```

## Configuration

La configuration est un fichier YAML situÃ© Ã  un emplacement unique : `~/.dso-secrets/config.yml` (sous Windows : `%USERPROFILE%\.dso-secrets\config.yml`).

Pour le crÃ©er, lancer :

```bash
dso-secrets init
```

La commande pose les questions une par une et Ã©crit le fichier. Options : `--mode local` (mode hors ligne), `--output <fichier>` (autre emplacement), `--force` (remplacer un fichier existant).

Le YAML ne contient jamais de secret : une clÃ© du type `client_secret`, `password` ou `token` est refusÃ©e.

Pour un container ou une CI, le contenu du YAML peut Ãªtre fourni dans la variable d'environnement `DSO_SECRETS_CONFIG_YAML`, ou le fichier montÃ© Ã  l'emplacement ci-dessus.

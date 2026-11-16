# dso-secrets

Package Python pour gérer des secrets dans OVHcloud OKMS (Secret Manager), ou dans un fichier isolé hors ligne.


## Installation

```bash
pip install "git+https://github.com/dso-conseils/dso-secrets.git@v0.4.0"
```

## Configuration

La configuration est un fichier YAML situé à un emplacement unique : `~/.dso-secrets/config.yml` (sous Windows : `%USERPROFILE%\.dso-secrets\config.yml`).

Pour le créer, lancer :

```bash
dso-secrets init
```

La commande pose les questions une par une et écrit le fichier. Options : `--mode isolated` (mode isolé hors ligne), `--output <fichier>` (autre emplacement), `--force` (remplacer un fichier existant).

En mode isolé, le fichier `.env` doit exister avant l'ouverture du store. Le
package fournit les mêmes opérations `list`, `get`, `exists`, `create`,
`update`, `upsert` et `delete` qu'en mode distant. Les modifications sont
écrites atomiquement et sérialisées au moyen d'un fichier `.lock` voisin ;
conserver les deux fichiers sur un stockage persistant partagé. Le fichier
de secrets n'est pas chiffré : protéger son répertoire et ne jamais le
versionner.

```yaml
mode: isolated
isolated:
  env_file: /chemin/prive/secrets.env
```

La configuration `mode: local` devient `mode: isolated`, et la section `local`
devient `isolated`. Les anciens fichiers `.env` sont lus et réécrits dans un
format versionné lors de la première modification ; mettre à jour tous leurs
lecteurs avant d'autoriser des écritures. L'ancien mode local ne fonctionne pas
avec cette version. Le mode isolé n'offre pas l'historique de versions d'OKMS.

Le YAML ne contient jamais de secret : une clé du type `client_secret`, `password` ou `token` est refusée.

Pour un container ou une CI, le contenu du YAML peut être fourni dans la variable d'environnement `DSO_SECRETS_CONFIG_YAML`, ou le fichier monté à l'emplacement ci-dessus.

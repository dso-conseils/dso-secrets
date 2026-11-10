# dso-secrets

CRUD de secrets **OVHcloud OKMS (Secret Manager)** pour les projets dso-conseils, avec deux modes :

- `remote` : lit et écrit dans OKMS avec un compte de service OAuth2.
- `local` : lit un fichier `.env` en lecture seule (machine sans internet).

Le package ne contient aucun secret. Les identifiants viennent des variables d'environnement.

## Installation

Le dépôt est public et ne contient aucun secret : aucun jeton n'est nécessaire, ni sur un poste, ni en CI, ni dans un container.

```bash
pip install "git+https://github.com/dso-conseils/dso-secrets.git@v0.1.0"
```

Figer toujours un tag (`@v0.1.0`).

## Configuration

Le YAML est toujours au **même endroit** : `~/.dso-secrets/config.yml` (sous Windows `C:\Users\<toi>\.dso-secrets\config.yml`). Le package n'en installe aucun et le code ne contient aucune valeur : tout vient de ce fichier.

Pour le créer, lancer une fois :

```bash
dso-secrets init
```

La commande pose les questions une par une, sans valeur proposée, écrit le fichier et affiche son chemin. `--force` remplace un fichier existant, `--mode local` prépare le mode hors ligne, `--output` écrit ailleurs.

Résultat (exemple de forme, les valeurs sont les tiennes) :

```yaml
mode: remote # remote ou local

remote:
  okms_id: ...                 # obligatoire
  api_url: ...                 # obligatoire
  token_url: ...               # obligatoire
  read_user_env: ...           # obligatoire : NOM de la variable contenant le client_id de lecture
  read_pass_env: ...           # obligatoire : NOM de la variable contenant le client_secret de lecture
  write_secret: ...            # facultatif : chemin du secret OKMS du compte d'écriture
  max_versions: 3              # facultatif

local:
  env_file: ...
```

Seule la section correspondant à `mode` est lue. Une clé du type `client_secret`, `password` ou `token` est refusée : le YAML ne contient jamais de secret.

### Où le package lit le YAML (premier trouvé)

1. `--config <fichier>` (option de la commande).
2. `DSO_SECRETS_CONFIG_YAML` : le **contenu** du YAML en variable (secret GitHub, Secret ou ConfigMap Kubernetes exposé en variable, `docker run -e`).
3. `~/.dso-secrets/config.yml`. Dans un container, monter le fichier à cet emplacement.
### Identifiants

| Variable | Contenu |
|---|---|
| `DSO_OKMS_USER` / `DSO_OKMS_PASS` | `client_id` / `client_secret` du compte de service en **lecture** (les noms de variables sont ceux déclarés dans le YAML) |

Le compte d'**écriture** n'est jamais passé en variable : ses `client_id` et `client_secret` sont lus dans le secret OKMS `remote.write_secret`, qui doit contenir ces deux clés. Ce secret est donc lisible par le compte de lecture, sauf si la politique IAM le restreint (filtrage par chemin non testé).

## Utilisation Python

```python
from dso_secrets import open_store

store = open_store()
store.list("infra-ovh/main/")
store.get("infra-ovh/main/argocd-admin-password")          # {"value": "..."}
store.get("app/main/db-credentials", "password")           # une clé
store.create("app/main/db-credentials", {"user": "u", "password": "p"})
store.update("app/main/db-credentials", {"user": "u", "password": "p2"})   # nouvelle version
store.upsert("app/main/db-credentials", {...})             # "created" ou "updated"
store.delete("app/main/db-credentials")
store.export_local("./dso-secrets.env", prefix="app/")     # copie hors ligne
```

Un secret est un ensemble de paires clé/valeur. `create` fixe `maxVersions` (`remote.max_versions`, 3 par défaut) pour plafonner le coût (0,03 € HT par version et par mois). `update` ajoute une version, OKMS élague les plus anciennes. Il n'y a pas de gestion explicite des versions.

## Ligne de commande

```bash
dso-secrets list [prefixe]
dso-secrets get <chemin> [--key CLE]
dso-secrets create|update|upsert <chemin> --set cle=valeur [--set ...]
echo '{"user":"u","password":"p"}' | dso-secrets upsert <chemin> --stdin-json
dso-secrets delete <chemin> --yes
dso-secrets export <fichier.env> [--prefix app/]
```

Préférer `--stdin-json` à `--set` pour les valeurs sensibles (l'historique du shell conserve les arguments).

### GitHub Actions

```yaml
- run: pip install "git+https://github.com/dso-conseils/dso-secrets.git@v0.1.0"
- run: dso-secrets get infra-ovh/main/argocd-admin-password --key value --github-env ARGOCD_ADMIN_PASSWORD
  env:
    DSO_OKMS_USER: ${{ secrets.DSO_OKMS_USER }}
    DSO_OKMS_PASS: ${{ secrets.DSO_OKMS_PASS }}
    DSO_SECRETS_CONFIG_YAML: ${{ vars.DSO_SECRETS_CONFIG_YAML }}
```

`--github-env` écrit la valeur dans `GITHUB_ENV` et la masque dans les journaux.

## Mode local (sans internet)

1. En ligne, sur un poste autorisé : `dso-secrets export ./dso-secrets.env --prefix infra-ovh/`.
2. Copier le fichier sur la machine isolée (container : monter en secret, `/run/secrets/dso-secrets.env`).
3. Configurer `mode: local` et `local.env_file`.

Format : une ligne `chemin#cle=valeur` (retours à la ligne écrits `\n`). Le fichier est en clair, avec droits restreints à l'utilisateur à l'export (`chmod 600`, `icacls` sous Windows). Il est en **lecture seule** : `create`, `update` et `delete` sont refusés. Il se périme : relancer l'export après un changement dans OKMS.

## Organisation des chemins

`<projet>/<environnement>/<nom-du-secret>`, en minuscules avec des tirets.

```
infra-ovh/main/argocd-admin-password
infra-ovh/main/state-s3-main
dso-conseils/accounts/okms-write        # compte de service d'écriture : client_id + client_secret
```

Un secret regroupe les clés liées (par exemple `user` et `password`) plutôt qu'un secret par clé. L'API de liste ne filtre pas par chemin : le filtrage par préfixe se fait côté client.

## Droits IAM nécessaires

| Compte | Actions |
|---|---|
| lecture | `okms:apiovh:secret/get`, `okms:apiovh:secret/version/getData` |
| écriture | `okms:apiovh:secret/get`, `secret/create`, `secret/edit`, `secret/updateMetadata`, `secret/version/create` |
| suppression | `okms:apiovh:secret/delete` (à donner au compte d'écriture si `delete` est utilisé) |

## Limites connues

- Les routes de création avec `metadata.maxVersions`, de mise à jour et de suppression sont testées contre un simulateur, pas contre OKMS (seules la liste et la lecture ont été validées en réel).
- Le curseur de pagination est lu dans l'en-tête `X-Pagination-Cursor-Next` (non vérifié : le domaine de test n'a que 13 secrets).
- Le jeton OAuth2 dure environ 1 h ; le package le renouvelle.
- Le mode local n'a aucune protection au-delà des droits du fichier.

## Développement

```bash
pip install -e ".[test]"
pytest
```


"""Ligne de commande : dso-secrets get|list|create|update|upsert|delete|export."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import DsoSecretsError, open_store
from .config import config_path, write_config


def _parse_pairs(pairs: List[str]) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise DsoSecretsError(f"'{pair}' invalide : attendu cle=valeur.")
        data[key] = value
    return data


def _read_data(args: argparse.Namespace) -> Dict[str, str]:
    if args.stdin_json:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise DsoSecretsError("Le JSON lu sur stdin doit etre un objet.")
        return {str(k): str(v) for k, v in payload.items()}
    if not args.set:
        raise DsoSecretsError("Fournir --set cle=valeur (repetable) ou --stdin-json.")
    return _parse_pairs(args.set)


def _write_github_env(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_ENV")
    if not target:
        raise DsoSecretsError("GITHUB_ENV absent : --github-env est reserve a GitHub Actions.")
    print(f"::add-mask::{value}")
    delimiter = "DSO_EOF_" + os.urandom(8).hex()
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


REMOTE_PROMPTS = (
    ("okms_id", "ID du domaine OKMS", True, None),
    ("api_url", "URL de l'API OVHcloud", True, "https://api.eu.ovhcloud.com/v2"),
    ("token_url", "URL du jeton OAuth2", True, "https://www.ovh.com/auth/oauth2/token"),
    ("read_user_env", "Nom de la variable d'environnement du client_id de lecture", True, None),
    ("read_pass_env", "Nom de la variable d'environnement du client_secret de lecture", True, None),
    ("write_secret", "Chemin du secret OKMS du compte d'ecriture (facultatif)", False, None),
    ("max_versions", "Nombre maximum de versions par secret", True, "3"),
)


def _ask(label: str, required: bool, default: Optional[str] = None) -> Optional[str]:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{label}{suffix} : ").strip() or (default or "")
        if answer or not required:
            return answer or None
        print("Valeur obligatoire.")


def init_config(args: argparse.Namespace) -> int:
    target = Path(args.output) if args.output else config_path()
    if target.exists() and not args.force:
        raise DsoSecretsError(f"{target} existe deja : utiliser --force pour le remplacer.")
    if args.mode == "local":
        data: Dict[str, object] = {"mode": "local", "local": {"env_file": _ask("Chemin du fichier .env local", True)}}
    else:
        remote: Dict[str, object] = {}
        for key, label, required, default in REMOTE_PROMPTS:
            value = _ask(label, required, default)
            if value is not None:
                remote[key] = int(value) if key == "max_versions" else value
        data = {"mode": "remote", "remote": remote}
    print(f"Configuration ecrite : {write_config(data, target, args.force)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dso-secrets", description=__doc__)
    parser.add_argument("--config", help="chemin du YAML (sinon DSO_SECRETS_CONFIG_YAML, puis ~/.dso-secrets/config.yml)")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="creer le YAML (~/.dso-secrets/config.yml) en posant les questions")
    init.add_argument("--mode", choices=["remote", "local"], default="remote")
    init.add_argument("--output", help="ecrire ailleurs que dans ~/.dso-secrets/config.yml")
    init.add_argument("--force", action="store_true", help="remplacer un fichier existant")

    get = sub.add_parser("get", help="lire un secret (JSON) ou une cle")
    get.add_argument("path")
    get.add_argument("--key")
    get.add_argument("--github-env", metavar="NAME", help="exporte la cle dans GITHUB_ENV (masquee)")

    lst = sub.add_parser("list", help="lister les chemins")
    lst.add_argument("prefix", nargs="?", default="")

    for name in ("create", "update", "upsert"):
        cmd = sub.add_parser(name)
        cmd.add_argument("path")
        cmd.add_argument("--set", action="append", metavar="CLE=VALEUR")
        cmd.add_argument("--stdin-json", action="store_true", help="lit un objet JSON sur stdin")

    delete = sub.add_parser("delete")
    delete.add_argument("path")
    delete.add_argument("--yes", action="store_true", help="confirme la suppression")

    export = sub.add_parser("export", help="copie hors ligne (mode remote) vers un fichier .env")
    export.add_argument("output")
    export.add_argument("--prefix", default="")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        return init_config(args)
    store = open_store(config_path=args.config)
    if args.command == "get":
        value = store.get(args.path, args.key)
        if args.github_env:
            if args.key is None:
                raise DsoSecretsError("--github-env demande --key.")
            _write_github_env(args.github_env, value)
        else:
            print(value if args.key else json.dumps(value, indent=2, ensure_ascii=False))
    elif args.command == "list":
        print("\n".join(store.list(args.prefix)))
    elif args.command == "create":
        store.create(args.path, _read_data(args))
        print(f"created: {args.path}")
    elif args.command == "update":
        store.update(args.path, _read_data(args))
        print(f"updated: {args.path}")
    elif args.command == "upsert":
        print(f"{store.upsert(args.path, _read_data(args))}: {args.path}")
    elif args.command == "delete":
        if not args.yes:
            raise DsoSecretsError("Suppression non confirmee : ajouter --yes.")
        store.delete(args.path)
        print(f"deleted: {args.path}")
    elif args.command == "export":
        count = store.export_local(args.output, args.prefix)
        print(f"exported {count} secret(s) -> {args.output}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except DsoSecretsError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

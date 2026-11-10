"""Ligne de commande : dso-secrets get|list|create|update|upsert|delete|export."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

from . import DsoSecretsError, open_store


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dso-secrets", description=__doc__)
    parser.add_argument("--config", help="chemin du YAML (sinon DSO_SECRETS_CONFIG_YAML, DSO_SECRETS_CONFIG, ./dso-secrets.yml, ~/.dso-secrets.yml)")
    sub = parser.add_subparsers(dest="command", required=True)

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

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finwise_model.runtime_engine import engine_status
from finwise_model.runtime_registry import (
    DEFAULT_MODEL_NAME,
    copy_model,
    delete_model,
    list_models,
    load_model,
    parse_modelfile,
    save_model,
)


def _cmd_list(_: argparse.Namespace) -> int:
    for model in list_models():
        print(f"{model.name}\t{model.family}\t{model.parameter_size}\t{model.modified_at}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    model = load_model(args.model)
    print(json.dumps(model.to_ollama_tag(), indent=2))
    if args.full:
        print(json.dumps(model.__dict__, indent=2))
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    source = Path(args.file)
    if not source.exists():
        raise SystemExit(f"Modelfile not found: {source}")
    model = parse_modelfile(source.read_text(encoding="utf-8"), default_name=args.name or DEFAULT_MODEL_NAME)
    if args.name:
        model = model.__class__(**{**model.__dict__, "name": args.name})
    path = save_model(model)
    print(f"Created {model.name} at {path}")
    return 0


def _cmd_copy(args: argparse.Namespace) -> int:
    copied = copy_model(args.source, args.destination)
    print(f"Copied {args.source} to {copied.name}")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    if not delete_model(args.model):
        raise SystemExit(f"Model not found: {args.model}")
    print(f"Deleted {args.model}")
    return 0


def _cmd_engine(args: argparse.Namespace) -> int:
    model = load_model(args.model)
    print(json.dumps(engine_status(model), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Finwise local model runtime CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List local Finwise runtime models.")
    list_parser.set_defaults(func=_cmd_list)

    show_parser = subparsers.add_parser("show", help="Show a local model descriptor.")
    show_parser.add_argument("model", nargs="?", default=DEFAULT_MODEL_NAME)
    show_parser.add_argument("--full", action="store_true", help="Print the full descriptor.")
    show_parser.set_defaults(func=_cmd_show)

    create_parser = subparsers.add_parser("create", help="Create a model descriptor from a Finwise Modelfile.")
    create_parser.add_argument("name", nargs="?", help="Model name, for example finwise-scratch:0.2.")
    create_parser.add_argument("-f", "--file", default="FinwiseModelfile", help="Path to the Finwise Modelfile.")
    create_parser.set_defaults(func=_cmd_create)

    copy_parser = subparsers.add_parser("copy", help="Copy a local model descriptor.")
    copy_parser.add_argument("source")
    copy_parser.add_argument("destination")
    copy_parser.set_defaults(func=_cmd_copy)

    delete_parser = subparsers.add_parser("delete", help="Delete a local model descriptor.")
    delete_parser.add_argument("model")
    delete_parser.set_defaults(func=_cmd_delete)

    engine_parser = subparsers.add_parser("engine", help="Show the selected inference backend for a model.")
    engine_parser.add_argument("model", nargs="?", default=DEFAULT_MODEL_NAME)
    engine_parser.set_defaults(func=_cmd_engine)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json

from .config import get_settings
from .service import create_target, list_targets, run_target


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-target")
    add.add_argument("--name", required=True)
    add.add_argument("--url", required=True)
    add.add_argument("--category", default="restoration")
    add.add_argument("--path", action="append", default=[])
    add.add_argument("--frequency-hours", type=int, default=168)
    run = sub.add_parser("run")
    run.add_argument("target_id")
    sub.add_parser("list")
    args = parser.parse_args()
    if args.command == "add-target":
        result = create_target({
            "name": args.name,
            "url": args.url,
            "category": args.category,
            "additional_paths": args.path,
            "frequency_hours": args.frequency_hours,
        })
    elif args.command == "run":
        result = run_target(get_settings(), args.target_id)
    else:
        result = list_targets()
    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[3]


def memory_ui_args(bank: str, port: int, open_browser: bool) -> list[str]:
    args = ["memory-ui", "--bank", bank, "--serve", "--port", str(port)]
    if open_browser:
        args.append("--open")
    return args


def _load_hindsight_main() -> Callable[[list[str]], int]:
    from hindsight_lite.cli import main as hindsight_main

    return hindsight_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the editable hindsight-lite memory tree.")
    parser.add_argument("--bank", default="codex")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(plugin_root()))
    try:
        hindsight_main = _load_hindsight_main()
    except ModuleNotFoundError:
        print(
            "hindsight-lite is unavailable from this skill path; reinstall the hindsight-lite Codex plugin.",
            file=sys.stderr,
        )
        return 1

    return hindsight_main(memory_ui_args(bank=args.bank, port=args.port, open_browser=not args.no_open))


if __name__ == "__main__":
    raise SystemExit(main())

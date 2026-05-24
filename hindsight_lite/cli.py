from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.recall import format_recall_for_codex, recall
from hindsight_lite.reflection import create_reflection_packet
from hindsight_lite.store import LocalMemoryStore


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hindsight_lite")
    parser.add_argument("--home", type=Path, default=None, help="Override hindsight-lite home directory.")
    subparsers = parser.add_subparsers(required=True)

    retain_parser = subparsers.add_parser("retain", help="Append session memory.")
    _add_bank_arg(retain_parser)
    retain_parser.add_argument("--session-id", required=True)
    retain_parser.add_argument("--content", required=True)
    retain_parser.set_defaults(handler=_cmd_retain)

    agent_retain_parser = subparsers.add_parser("agent_knowledge_retain", help="Append session memory.")
    _add_bank_arg(agent_retain_parser)
    agent_retain_parser.add_argument("--session-id", required=True)
    agent_retain_parser.add_argument("--content", required=True)
    agent_retain_parser.set_defaults(handler=_cmd_retain)

    recall_parser = subparsers.add_parser("recall", help="Recall local memory.")
    _add_bank_arg(recall_parser)
    recall_parser.add_argument("--max-results", type=int, default=5)
    recall_parser.add_argument("query")
    recall_parser.set_defaults(handler=_cmd_recall)

    agent_recall_parser = subparsers.add_parser("agent_knowledge_recall", help="Recall local memory.")
    _add_bank_arg(agent_recall_parser)
    agent_recall_parser.add_argument("--max-results", type=int, default=5)
    agent_recall_parser.add_argument("query")
    agent_recall_parser.set_defaults(handler=_cmd_recall)

    reflect_parser = subparsers.add_parser("reflect", help="Write a reflection request packet.")
    _add_bank_arg(reflect_parser)
    reflect_parser.add_argument("--session-id", required=True)
    reflect_parser.add_argument("--max-results", type=int, default=5)
    reflect_parser.add_argument("query")
    reflect_parser.set_defaults(handler=_cmd_reflect)

    agent_reflect_parser = subparsers.add_parser("agent_knowledge_reflect", help="Write a reflection request packet.")
    _add_bank_arg(agent_reflect_parser)
    agent_reflect_parser.add_argument("--session-id", required=True)
    agent_reflect_parser.add_argument("--max-results", type=int, default=5)
    agent_reflect_parser.add_argument("query")
    agent_reflect_parser.set_defaults(handler=_cmd_reflect)

    knowledge_parser = subparsers.add_parser("knowledge", help="Manage Markdown knowledge pages.")
    knowledge_subparsers = knowledge_parser.add_subparsers(required=True)

    list_parser = knowledge_subparsers.add_parser("list", help="List pages.")
    _add_bank_arg(list_parser)
    list_parser.set_defaults(handler=_cmd_knowledge_list)

    agent_list_pages_parser = subparsers.add_parser("agent_knowledge_list_pages", help="List pages.")
    _add_bank_arg(agent_list_pages_parser)
    agent_list_pages_parser.set_defaults(handler=_cmd_knowledge_list)

    get_parser = knowledge_subparsers.add_parser("get", help="Get one page.")
    _add_bank_arg(get_parser)
    get_parser.add_argument("page_id")
    get_parser.set_defaults(handler=_cmd_knowledge_get)

    agent_get_page_parser = subparsers.add_parser("agent_knowledge_get_page", help="Get one page.")
    _add_bank_arg(agent_get_page_parser)
    agent_get_page_parser.add_argument("page_id")
    agent_get_page_parser.set_defaults(handler=_cmd_knowledge_get)

    write_parser = knowledge_subparsers.add_parser("write", help="Write one page from a Markdown file.")
    _add_bank_arg(write_parser)
    write_parser.add_argument("--id", required=True, dest="page_id")
    write_parser.add_argument("--title", default=None)
    write_parser.add_argument("--file", required=True, type=Path)
    write_parser.set_defaults(handler=_cmd_knowledge_write)

    return parser


def _add_bank_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bank", required=True)


def _store(args: argparse.Namespace) -> LocalMemoryStore:
    return LocalMemoryStore(home=args.home, bank_id=args.bank)


def _cmd_retain(args: argparse.Namespace) -> int:
    store = _store(args)
    event = SessionMemoryEvent(
        type="session_memory",
        id=f"session-{uuid4().hex}",
        timestamp=_utc_now(),
        bank_id=args.bank,
        session_id=args.session_id,
        source="codex",
        document_id=f"codex-{args.session_id}",
        content=args.content,
    )
    store.append_session_event(event)
    print(event.id)
    return 0


def _cmd_recall(args: argparse.Namespace) -> int:
    results = recall(_store(args), args.query, max_results=args.max_results)
    print(
        format_recall_for_codex(
            results,
            preamble="Relevant hindsight-lite memory:",
        )
    )
    return 0


def _cmd_reflect(args: argparse.Namespace) -> int:
    packet = create_reflection_packet(
        store=_store(args),
        session_id=args.session_id,
        query=args.query,
        max_results=args.max_results,
    )
    print(json.dumps(asdict(packet), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_knowledge_list(args: argparse.Namespace) -> int:
    for page in _store(args).list_pages():
        print(f"{page.id}\t{page.title}")
    return 0


def _cmd_knowledge_get(args: argparse.Namespace) -> int:
    page = _store(args).get_page(args.page_id)
    print(page.content)
    return 0


def _cmd_knowledge_write(args: argparse.Namespace) -> int:
    content = args.file.read_text(encoding="utf-8")
    title = args.title or args.page_id
    page = _store(args).write_page(page_id=args.page_id, title=title, content=content)
    print(page.path)
    return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    sys.exit(main())

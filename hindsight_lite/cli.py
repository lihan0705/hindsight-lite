from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hindsight_lite.codex_memory import import_codex_memories
from hindsight_lite.demo_memory import DemoMemoryExistsError, seed_demo_memory
from hindsight_lite.memory_ui import write_memory_ui
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

    codex_memory_parser = subparsers.add_parser("codex-memory", help="Import OpenAI Codex memory files.")
    codex_memory_subparsers = codex_memory_parser.add_subparsers(required=True)

    codex_memory_import_parser = codex_memory_subparsers.add_parser(
        "import", help="Import Codex memory files as pages."
    )
    _add_bank_arg(codex_memory_import_parser)
    codex_memory_import_parser.add_argument("--source-dir", type=Path, default=None)
    codex_memory_import_parser.add_argument("--dry-run", action="store_true")
    codex_memory_import_parser.set_defaults(handler=_cmd_codex_memory_import)

    agent_import_codex_memory_parser = subparsers.add_parser(
        "agent_knowledge_import_codex_memory",
        help="Import OpenAI Codex memory files as pages.",
    )
    _add_bank_arg(agent_import_codex_memory_parser)
    agent_import_codex_memory_parser.add_argument("--source-dir", type=Path, default=None)
    agent_import_codex_memory_parser.add_argument("--dry-run", action="store_true")
    agent_import_codex_memory_parser.set_defaults(handler=_cmd_codex_memory_import)

    memory_ui_parser = subparsers.add_parser("memory-ui", help="Generate a static local memory tree UI.")
    _add_bank_arg(memory_ui_parser)
    memory_ui_parser.add_argument("--output", type=Path, default=None)
    memory_ui_parser.set_defaults(handler=_cmd_memory_ui)

    demo_memory_parser = subparsers.add_parser("demo-memory", help="Generate demo memory for UI inspection.")
    demo_memory_subparsers = demo_memory_parser.add_subparsers(required=True)
    demo_seed_parser = demo_memory_subparsers.add_parser("seed", help="Seed five demo memory history items.")
    _add_bank_arg(demo_seed_parser)
    demo_seed_parser.add_argument("--overwrite", action="store_true")
    demo_seed_parser.add_argument("--write-ui", action="store_true")
    demo_seed_parser.add_argument("--output", type=Path, default=None)
    demo_seed_parser.set_defaults(handler=_cmd_demo_memory_seed)

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


def _cmd_codex_memory_import(args: argparse.Namespace) -> int:
    result = import_codex_memories(store=_store(args), source_dir=args.source_dir, dry_run=args.dry_run)
    for page_id in result.imported_pages:
        print(page_id)
    for skipped_file in result.skipped_files:
        print(f"skipped\t{skipped_file}", file=sys.stderr)
    return 0


def _cmd_memory_ui(args: argparse.Namespace) -> int:
    output_path = write_memory_ui(store=_store(args), output_path=args.output)
    print(output_path)
    return 0


def _cmd_demo_memory_seed(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        result = seed_demo_memory(store=store, overwrite=args.overwrite)
    except DemoMemoryExistsError as exc:
        print(f"demo memory already exists; pass --overwrite to replace: {exc}", file=sys.stderr)
        return 1

    for page_id in result.pages:
        print(f"page\t{page_id}")
    for session_id in result.sessions:
        print(f"session\t{session_id}")
    for reflection_id in result.reflections:
        print(f"reflection\t{reflection_id}")
    for index_file in result.index_files:
        print(f"index\t{index_file}")
    if args.write_ui:
        print(f"ui\t{write_memory_ui(store=store, output_path=args.output)}")
    return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    sys.exit(main())

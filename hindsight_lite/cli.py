from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hindsight_lite.codex_memory import import_codex_memories
from hindsight_lite.demo_memory import DemoMemoryExistsError, seed_demo_memory
from hindsight_lite.index import rebuild_recall_index, recall_index_path, recall_index_status
from hindsight_lite.memory_ui import write_memory_ui
from hindsight_lite.memory_ui_server import create_memory_ui_server, memory_ui_server_url
from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.recall import format_recall_for_codex, recall
from hindsight_lite.recall_eval import RecallEvalExistsError, run_recall_eval
from hindsight_lite.reflection import ReflectionResultError, create_reflection_packet, write_reflection_result_from_file
from hindsight_lite.reflection_cleanup import scan_reflection_cleanup
from hindsight_lite.reflection_dataset import export_reflection_dataset
from hindsight_lite.store import LocalMemoryStore, UnsafeReflectionIdError


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

    reflection_result_parser = subparsers.add_parser(
        "reflection-result",
        help="Write a reflection_result JSON file into local memory.",
    )
    reflection_result_subparsers = reflection_result_parser.add_subparsers(required=True)
    reflection_result_write_parser = reflection_result_subparsers.add_parser(
        "write",
        help="Write one reflection_result JSON file.",
    )
    _add_bank_arg(reflection_result_write_parser)
    reflection_result_write_parser.add_argument("--file", required=True, type=Path)
    reflection_result_write_parser.set_defaults(handler=_cmd_reflection_result_write)

    reflection_dataset_parser = subparsers.add_parser(
        "reflection-dataset",
        help="Export paired reflection_request and reflection_result records.",
    )
    reflection_dataset_subparsers = reflection_dataset_parser.add_subparsers(required=True)
    reflection_dataset_export_parser = reflection_dataset_subparsers.add_parser(
        "export",
        help="Export paired reflection data as JSONL.",
    )
    _add_bank_arg(reflection_dataset_export_parser)
    reflection_dataset_export_parser.add_argument("--output", required=True, type=Path)
    reflection_dataset_export_parser.set_defaults(handler=_cmd_reflection_dataset_export)

    reflection_cleanup_parser = subparsers.add_parser(
        "reflection-cleanup",
        help="Find low-quality reflection candidates without deleting files.",
    )
    reflection_cleanup_subparsers = reflection_cleanup_parser.add_subparsers(required=True)
    reflection_cleanup_scan_parser = reflection_cleanup_subparsers.add_parser(
        "scan",
        help="Report repeated or noisy reflection records.",
    )
    _add_bank_arg(reflection_cleanup_scan_parser)
    reflection_cleanup_scan_parser.set_defaults(handler=_cmd_reflection_cleanup_scan)

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

    index_parser = subparsers.add_parser("index", help="Inspect or rebuild the local recall index.")
    index_subparsers = index_parser.add_subparsers(required=True)

    index_status_parser = index_subparsers.add_parser("status", help="Show local recall index status.")
    _add_bank_arg(index_status_parser)
    index_status_parser.set_defaults(handler=_cmd_index_status)

    index_rebuild_parser = index_subparsers.add_parser("rebuild", help="Rebuild the local recall index.")
    _add_bank_arg(index_rebuild_parser)
    index_rebuild_parser.set_defaults(handler=_cmd_index_rebuild)

    memory_ui_parser = subparsers.add_parser("memory-ui", help="Generate a static local memory tree UI.")
    _add_bank_arg(memory_ui_parser)
    memory_ui_parser.add_argument("--output", type=Path, default=None)
    memory_ui_parser.add_argument("--open", action="store_true", help="Open the generated HTML file in a browser.")
    memory_ui_parser.add_argument("--serve", action="store_true", help="Serve an editable UI over local HTTP.")
    memory_ui_parser.add_argument("--host", default=None, help="Server bind address; WSL defaults to its private IPv4.")
    memory_ui_parser.add_argument("--port", type=int, default=0, help="Local server port; 0 selects a free port.")
    memory_ui_parser.set_defaults(handler=_cmd_memory_ui)

    demo_memory_parser = subparsers.add_parser("demo-memory", help="Generate demo memory for UI inspection.")
    demo_memory_subparsers = demo_memory_parser.add_subparsers(required=True)
    demo_seed_parser = demo_memory_subparsers.add_parser("seed", help="Seed five demo memory history items.")
    _add_bank_arg(demo_seed_parser)
    demo_seed_parser.add_argument("--overwrite", action="store_true")
    demo_seed_parser.add_argument("--write-ui", action="store_true")
    demo_seed_parser.add_argument("--output", type=Path, default=None)
    demo_seed_parser.set_defaults(handler=_cmd_demo_memory_seed)

    recall_eval_parser = subparsers.add_parser("recall-eval", help="Run a local recall quality fixture.")
    recall_eval_subparsers = recall_eval_parser.add_subparsers(required=True)
    recall_eval_run_parser = recall_eval_subparsers.add_parser("run", help="Seed and run five recall eval cases.")
    _add_bank_arg(recall_eval_run_parser)
    recall_eval_run_parser.add_argument("--overwrite", action="store_true")
    recall_eval_run_parser.add_argument("--max-results", type=int, default=3)
    recall_eval_run_parser.set_defaults(handler=_cmd_recall_eval_run)

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


def _cmd_reflection_result_write(args: argparse.Namespace) -> int:
    try:
        path = write_reflection_result_from_file(store=_store(args), path=args.file)
    except (json.JSONDecodeError, ReflectionResultError, UnsafeReflectionIdError) as exc:
        print(f"invalid reflection_result: {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


def _cmd_reflection_dataset_export(args: argparse.Namespace) -> int:
    result = export_reflection_dataset(store=_store(args), output_path=args.output)
    print(f"{result.output_path}\t{result.example_count}")
    return 0


def _cmd_reflection_cleanup_scan(args: argparse.Namespace) -> int:
    report = scan_reflection_cleanup(_store(args))
    print(f"reflection-cleanup\t{len(report.candidates)}/{report.scanned}")
    for candidate in report.candidates:
        print(
            "\t".join(
                [
                    "candidate",
                    candidate.id,
                    ",".join(candidate.issue_codes),
                    candidate.entry_state,
                    str(candidate.path),
                ]
            )
        )
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


def _cmd_index_status(args: argparse.Namespace) -> int:
    print(json.dumps(asdict(recall_index_status(_store(args))), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_index_rebuild(args: argparse.Namespace) -> int:
    store = _store(args)
    index = rebuild_recall_index(store)
    print(f"{recall_index_path(store)}\t{len(index.documents)}")
    return 0


def _cmd_memory_ui(args: argparse.Namespace) -> int:
    if args.serve:
        return _serve_memory_ui(args)

    output_path = write_memory_ui(store=_store(args), output_path=args.output)
    print(output_path)
    if args.open:
        try:
            _open_local_file(output_path)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"could not open memory tree UI: {exc}", file=sys.stderr)
            return 1
    return 0


def _serve_memory_ui(args: argparse.Namespace) -> int:
    server = create_memory_ui_server(store=_store(args), host=args.host or _default_memory_ui_host(), port=args.port)
    url = memory_ui_server_url(server)
    print(url, flush=True)
    if args.open:
        try:
            _open_target(url)
        except (OSError, subprocess.CalledProcessError) as exc:
            server.server_close()
            print(f"could not open memory tree UI: {exc}", file=sys.stderr)
            return 1

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _open_local_file(path: Path) -> None:
    _open_target(str(path.resolve()))


def _open_target(target: str) -> None:
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        command = ["open", target]
    elif _is_wsl():
        # Windows browsers can reach WSL localhost without exposing the HTML through a UNC file path.
        command = ["powershell.exe", "-NoProfile", "-Command", f"Start-Process -FilePath '{target}'"]
    else:
        command = ["xdg-open", target]
    subprocess.run(command, check=True)


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _default_memory_ui_host() -> str:
    if not _is_wsl():
        return "127.0.0.1"

    try:
        result = subprocess.run(
            ["hostname", "-I"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "127.0.0.1"

    for value in result.stdout.split():
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4 and address.is_private and not address.is_loopback:
            return str(address)
    return "127.0.0.1"


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


def _cmd_recall_eval_run(args: argparse.Namespace) -> int:
    try:
        result = run_recall_eval(store=_store(args), overwrite=args.overwrite, max_results=args.max_results)
    except RecallEvalExistsError as exc:
        print(f"recall eval memory already exists; pass --overwrite to replace: {exc}", file=sys.stderr)
        return 1

    print(f"recall-eval\t{result.passed}/{result.total}")
    for case in result.cases:
        status = "pass" if case.passed else "fail"
        print(
            "\t".join(
                [
                    status,
                    case.case_id,
                    f"expected={case.expected_source}:{case.expected_id}",
                    f"top={case.top_source}:{case.top_id}",
                    f"returned={','.join(case.returned_ids)}",
                ]
            )
        )
    return 0 if result.ok else 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    sys.exit(main())

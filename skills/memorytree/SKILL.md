---
name: memorytree
description: Open the editable hindsight-lite memory tree in a local browser. Use when the user asks to view, inspect, edit, or open their memory tree.
---

# Memory Tree

1. Use `codex` as the bank unless the user names another bank.
2. Start the bundled launcher in a long-running background terminal:

   ```bash
   python3 <skill-directory>/scripts/open_memorytree.py --bank codex
   ```

3. Read the printed `http://127.0.0.1:<port>/` URL and report it to the user.
4. Keep the terminal running while the user inspects or edits memory. Stop it only when requested.

The editable UI must use an `http://127.0.0.1` URL. A `memory-tree.html` path is a read-only static
snapshot and is not a successful result for this skill.

If automatic browser opening fails, restart the launcher with `--no-open`, keep the server running,
and give the localhost URL to the user. Do not fall back to a WSL UNC file path.

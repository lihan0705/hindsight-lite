---
name: memorytree
description: Open the editable hindsight-lite memory tree in a local browser. Use when the user asks to view, inspect, edit, or open their memory tree.
---

# Memory Tree

1. Resolve the plugin root as the directory two levels above this `SKILL.md`.
2. Use `codex` as the bank unless the user names another bank.
3. Start this command in a long-running background terminal:

   ```bash
   PYTHONPATH="<plugin-root>${PYTHONPATH:+:$PYTHONPATH}" python3 -m hindsight_lite memory-ui --bank codex --serve --open
   ```

4. Read the printed `http://127.0.0.1:<port>/` URL and report it to the user.
5. Keep the terminal running while the user inspects or edits memory. Stop it only when requested.

If automatic browser opening fails, restart without `--open`, keep the server running, and give the
localhost URL to the user. Do not fall back to a WSL UNC file path.

# Codex hook dashboard

Run `py -3 server.py`, then visit `http://127.0.0.1:8765`.

The dashboard groups events by session and breaks each session into the activity after every `UserPromptSubmit` event. Every hook first saves its payload locally, then immediately `POST`s it to the dashboard. Open pages receive that notification through a Server-Sent Events stream and refresh without a polling delay. If the dashboard is not running, the saved event appears after it starts.

`.codex/hooks.json` configures all 12 Codex lifecycle events to call `hook_recorder.py`. Start a new Codex session in this workspace and review/trust the hook configuration when asked. Events are stored in `hook_records/` with their full hook payload, including potential sensitive tool inputs; `hook_records/hook_invocations.jsonl` is a compact append-only verification log. The dashboard binds only to localhost.

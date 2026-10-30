"""Persist each Codex hook payload and immediately notify the local dashboard."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

RECORDS = Path(__file__).resolve().parent / "hook_records"
INVOCATION_LOG = RECORDS / "hook_invocations.jsonl"
DASHBOARD_NOTIFY_URL = "http://127.0.0.1:8765/api/events"


def notify_dashboard(event: dict) -> None:
    """Best effort: an unavailable dashboard must never break a Codex hook."""
    request = Request(
        DASHBOARD_NOTIFY_URL,
        data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=0.75):
            pass
    except (OSError, URLError):
        pass  # The persisted record will be shown after the dashboard starts.

def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict): payload = {"raw_payload": payload}
        now = datetime.now(timezone.utc)
        event = {"recorded_at": now.isoformat(timespec="milliseconds"), "event": payload.get("hook_event_name", "unknown"), "session_id": payload.get("session_id"), "payload": payload}
        RECORDS.mkdir(parents=True, exist_ok=True)
        # Keep a compact, append-only audit trail in addition to the complete
        # per-event payload files.  This makes it easy to confirm that a hook
        # ran without opening every individual record.
        with INVOCATION_LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps({
                "recorded_at": event["recorded_at"],
                "event": event["event"],
                "session_id": event["session_id"],
            }, ensure_ascii=False) + "\n")
        target = RECORDS / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
        notify_dashboard(event)
    except Exception as exc: print(f"Hook recorder failed: {exc}", file=sys.stderr)
    return 0

if __name__ == "__main__": raise SystemExit(main())

"""Run `py -3 server.py`, then open http://127.0.0.1:8765."""
from __future__ import annotations

import argparse
import json
import queue
import threading
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DIR = Path(__file__).resolve().parent / "hook_records"


class EventHub:
    """Fan out hook notifications to open dashboard pages."""

    def __init__(self):
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=20)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event: dict) -> None:
        message = json.dumps(event, ensure_ascii=False)
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                pass


def records(directory: Path) -> list[dict]:
    result = []
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            item["_file"] = path.name
            result.append(item)
        except (OSError, json.JSONDecodeError) as exc:
            result.append({"_file": path.name, "error": str(exc)})
    return result


def sessions(directory: Path) -> list[dict]:
    grouped = defaultdict(list)
    for event in records(directory):
        grouped[event.get("session_id") or "unknown"].append(event)
    return [
        {"session_id": session_id, "events": events}
        for session_id, events in sorted(
            grouped.items(), key=lambda pair: pair[1][-1].get("recorded_at", ""), reverse=True
        )
    ]


PAGE = r'''<!doctype html><meta charset="utf-8"><title>Codex hook events</title>
<style>
body{font:14px system-ui;margin:2rem;background:#101418;color:#e8edf2}button{padding:.4rem .8rem}
section,.turn{background:#171d23;margin:1rem 0;padding:1rem;border-radius:7px}.turn{border-left:4px solid #44b6e9}
.user-prompt{white-space:pre-wrap;word-break:break-word;background:#0b2737;color:#dcf3ff;padding:.8rem;border-radius:4px;font:15px system-ui}
small{color:#aebbc7}pre{white-space:pre-wrap;word-break:break-word;color:#b9e4ff;background:#0e1216;padding:.7rem;border-radius:4px}details{margin-top:.45rem}table{width:100%;border-collapse:collapse;background:#171d23}th,td{text-align:left;padding:.65rem;border-bottom:1px solid #2b3540;vertical-align:top}th{color:#aebbc7;font-weight:600}td{word-break:break-word}.event-message{white-space:pre-wrap}.event-row{cursor:pointer}.event-row:focus{outline:2px solid #44b6e9;outline-offset:-2px}.event-detail td{padding:0}.event-detail pre{margin:.5rem}
</style>
<h1>Codex hook events <button onclick="load()">Refresh</button> <small id="count"></small></h1><main id="app"></main>
<script>
const e=s=>String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const text=v=>typeof v==='string'?v:(v?JSON.stringify(v):'No prompt text supplied');
const promptText=x=>{const p=x.payload||{};return text(p.prompt??p.user_prompt??p.user_input??p.message??p.content??p.input??x.prompt)};
const show=x=>`<details><summary>${e(x.recorded_at)} — ${e(x.event)}</summary><pre>${e(JSON.stringify(x,null,2))}</pre></details>`;
function turns(events){const result=[];let current=null;for(const event of events){if(event.event==='UserPromptSubmit'){current={prompt:event,events:[event]};result.push(current)}else if(current){current.events.push(event)}}return result.reverse()}
function render(session){const list=turns(session.events);const attached=new Set(list.flatMap(t=>t.events));const loose=session.events.filter(x=>!attached.has(x));const content=list.map((turn,index)=>`<article class="turn"><small>User prompt ${index+1} · ${e(turn.prompt.recorded_at)} · ${turn.events.length} hook event(s)</small><h3>User prompt</h3><div class="user-prompt">${e(promptText(turn.prompt))}</div><h3>Complete records for this prompt</h3>${turn.events.map(show).join('')}</article>`).join('')+(loose.length?`<article class="turn"><h3>Other hook events</h3>${loose.map(show).join('')}</article>`:'')||'<p>No hook events captured in this session yet.</p>';return `<section><h2>Session <code>${e(session.session_id)}</code> <small>(${session.events.length} total events)</small></h2>${content}</section>`}
function eventMessage(event){return event.event==='UserPromptSubmit'?promptText(event):''}
function render(session){const rows=[...session.events].reverse().map(event=>`<tr class="event-row" tabindex="0" role="button" onclick="this.nextElementSibling.hidden=!this.nextElementSibling.hidden" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"><td><time>${e(event.recorded_at)}</time></td><td>${e(event.event)}</td><td class="event-message">${e(eventMessage(event))}</td></tr><tr class="event-detail" hidden><td colspan="3"><pre>${e(JSON.stringify(event,null,2))}</pre></td></tr>`).join('')||'<tr><td colspan="3">No hook events captured in this session yet.</td></tr>';return `<section><h2>Session <code>${e(session.session_id)}</code> <small>(${session.events.length} total events)</small></h2><table><thead><tr><th>Time</th><th>Event</th><th>Message</th></tr></thead><tbody>${rows}</tbody></table></section>`}
async function load(){const data=await(await fetch('/api/sessions',{cache:'no-store'})).json();count.textContent=data.length+' session(s)';app.innerHTML=data.map(render).join('')}
load();const stream=new EventSource('/api/stream');stream.onmessage=load;stream.onerror=()=>setTimeout(load,1000);
</script>'''


def handler(directory: Path, hub: EventHub):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            # Browsers routinely close an EventSource while a keepalive is pending.
            # Treat that normal disconnect as a completed request, not a traceback.
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def send_body(self, body: bytes, kind: str, code: HTTPStatus) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            endpoint = urlparse(self.path).path
            if endpoint == "/api/sessions":
                body, kind, code = json.dumps(sessions(directory), ensure_ascii=False).encode(), "application/json", HTTPStatus.OK
            elif endpoint == "/api/events":
                body, kind, code = json.dumps(records(directory), ensure_ascii=False).encode(), "application/json", HTTPStatus.OK
            elif endpoint in {"/", "/index.html"}:
                body, kind, code = PAGE.encode(), "text/html", HTTPStatus.OK
            elif endpoint == "/api/stream":
                self.stream_events()
                return
            else:
                body, kind, code = b"Not found\n", "text/plain", HTTPStatus.NOT_FOUND
            self.send_body(body, kind, code)

        def do_POST(self):
            if urlparse(self.path).path != "/api/events":
                self.send_body(b"Not found\n", "text/plain", HTTPStatus.NOT_FOUND)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                event = json.loads(self.rfile.read(size))
                if not isinstance(event, dict):
                    raise ValueError("event must be an object")
            except (ValueError, json.JSONDecodeError):
                self.send_body(b"Invalid JSON event\n", "text/plain", HTTPStatus.BAD_REQUEST)
                return
            hub.publish(event)
            self.send_body(b"Notified\n", "text/plain", HTTPStatus.ACCEPTED)

        def stream_events(self):
            subscriber = hub.subscribe()
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        message = subscriber.get(timeout=15)
                        self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                hub.unsubscribe(subscriber)

        def log_message(self, *_):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--records-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    args.records_dir.mkdir(parents=True, exist_ok=True)
    print(f"Serving {args.records_dir} at http://127.0.0.1:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), handler(args.records_dir, EventHub())).serve_forever()


if __name__ == "__main__":
    main()

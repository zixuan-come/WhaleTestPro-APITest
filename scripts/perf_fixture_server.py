"""Stateless synthetic target for CI only; no database or real credentials."""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MARKER = "whale-perf-core"


def response_for(method, path, headers, raw_body):
    parsed = urlsplit(path)
    content_type = headers.get("Content-Type", "").split(";", 1)[0]
    try:
        text = raw_body.decode("utf-8")
        if not raw_body:
            body = ""
        elif content_type == "application/json":
            body = json.loads(text)
        elif content_type == "application/x-www-form-urlencoded":
            body = {key: values[0] for key, values in parse_qs(text, keep_blank_values=True).items()}
        else:
            body = text
    except (ValueError, UnicodeError):
        return 400, {"fixture": MARKER}
    base = {"fixture": MARKER}
    if method == "GET" and parsed.path == "/health":
        return 200, base
    if method == "POST" and parsed.path == "/echo":
        return 200, {**base, "method": method, "header": headers.get("X-Fixture"),
                     "query": parse_qs(parsed.query).get("source", [None])[0], "body": body}
    if method == "POST" and parsed.path == "/login":
        if not isinstance(body, dict) or not isinstance(body.get("owner"), str) or not body["owner"]:
            return 400, base
        return 200, {**base, "token": "fixture-" + body["owner"]}
    token = headers.get("Authorization", "")
    if not token.startswith("Bearer fixture-"):
        return 401, base
    order_id = hashlib.sha256(token.encode()).hexdigest()[:24]
    if method == "POST" and parsed.path == "/orders":
        if not (isinstance(body, dict) and type(body.get("quantity")) is int and body["quantity"] == 1
                and body.get("active") is True and headers.get("X-Fixture") == "perf-core"
                and parse_qs(parsed.query).get("source") == ["apitest"]):
            return 400, base
        return 201, {**base, "id": order_id}
    if method == "GET" and parsed.path == "/orders/" + order_id:
        return 200, {**base, "id": order_id}
    return 404, base


class Handler(BaseHTTPRequestHandler):
    def dispatch(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 262144:
            self.send_error(413)
            return
        status, body = response_for(self.command, self.path, self.headers, self.rfile.read(length))
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = dispatch

    def log_message(self, *_args):
        # Avoid credential, variable and dynamic-path logging even for fixtures.
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()

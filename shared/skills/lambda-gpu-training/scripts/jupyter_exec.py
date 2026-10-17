#!/usr/bin/env python3
"""Run commands and move files on a Lambda instance through its Jupyter server.

Set JUPYTER_URL_FILE to a 0600 file holding the instance's Jupyter URL (token included), as
written by `lambda_api.py wait --save-url`. Needs the `websocket-client` package locally.

  jupyter_exec.py sh  '<command>'              run and print output (PYTHON -> kernel interpreter)
  jupyter_exec.py bg  '<command>' '<logfile>'  start detached, output to logfile on the instance
  jupyter_exec.py put <local> '<remote>'       upload a text file (creates parent directories)
  jupyter_exec.py putc <local> <remote-path>   upload via the contents API (no kernel needed)
  jupyter_exec.py get <remote-path> <local>    download; .pt/.bin/.pth/.gz/.zip are fetched as base64
  jupyter_exec.py ls  <remote-dir>             list a directory via the contents API

Remote paths for put/bg/sh may use ~; contents-API paths are relative to the Jupyter root.
"""
import base64
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request
import uuid

BINARY = {".pt", ".pth", ".bin", ".gz", ".zip", ".npy", ".npz", ".safetensors"}
UA = "curl/8.7.1"  # the Jupyter proxy rejects Python's default User-Agent with 403


def load_url():
    f = os.environ.get("JUPYTER_URL_FILE")
    if not f or not os.path.exists(f):
        sys.exit("JUPYTER_URL_FILE is not set or does not exist")
    parsed = urllib.parse.urlparse(pathlib.Path(f).read_text().strip())
    token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
    if not token:
        sys.exit("the saved Jupyter URL has no token")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}", token, pathlib.Path(f)


BASE, TOKEN, URL_FILE = load_url()
AUTH = f"token {TOKEN}"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, method=method, data=data,
        headers={"Authorization": AUTH, "Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def kernel_id():
    f = URL_FILE.with_suffix(".kernel")
    if f.exists():
        kid = f.read_text().strip()
        if any(k["id"] == kid for k in api("GET", "/api/kernels")):
            return kid
    kid = api("POST", "/api/kernels", {"name": "python3"})["id"]
    f.write_text(kid)
    return kid


def execute(code, timeout=3600):
    import websocket  # websocket-client

    ws_url = BASE.replace("https://", "wss://").replace("http://", "ws://") + f"/api/kernels/{kernel_id()}/channels"
    ws = websocket.create_connection(ws_url, header=[f"Authorization: {AUTH}", f"User-Agent: {UA}"], timeout=timeout)
    msg_id = uuid.uuid4().hex
    ws.send(json.dumps({
        "header": {"msg_id": msg_id, "username": "u", "session": uuid.uuid4().hex,
                   "msg_type": "execute_request", "version": "5.3"},
        "parent_header": {}, "metadata": {}, "channel": "shell",
        "content": {"code": code, "silent": False, "store_history": False,
                    "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
    }))
    while True:
        m = json.loads(ws.recv())
        if m.get("parent_header", {}).get("msg_id") != msg_id:
            continue
        kind, content = m["msg_type"], m["content"]
        if kind == "stream":
            print(content["text"], end="")
        elif kind == "error":
            print("\n".join(content["traceback"]))
        elif kind == "status" and content["execution_state"] == "idle":
            break
    ws.close()


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    mode = args[0]
    if mode == "sh":
        execute("import subprocess, sys\n"
                f"r = subprocess.run({args[1]!r}.replace('PYTHON', sys.executable), shell=True, capture_output=True, text=True)\n"
                "print(r.stdout[-8000:]); print(r.stderr[-3000:])\n")
    elif mode == "bg":
        execute("import subprocess, sys, os\n"
                f"log = open(os.path.expanduser({args[2]!r}), 'w')\n"
                f"p = subprocess.Popen({args[1]!r}.replace('PYTHON', sys.executable), shell=True, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)\n"
                "print('started pid', p.pid)\n")
    elif mode == "put":
        text = pathlib.Path(args[1]).read_text()
        execute("import os\n"
                f"p = os.path.expanduser({args[2]!r})\n"
                "os.makedirs(os.path.dirname(p) or '.', exist_ok=True)\n"
                f"print('wrote', open(p, 'w').write({text!r}), 'bytes to', p)\n")
    elif mode == "putc":
        doc = api("PUT", f"/api/contents/{args[2]}", {"type": "file", "format": "text", "content": pathlib.Path(args[1]).read_text()})
        print("uploaded", doc["path"], doc["size"], "bytes")
    elif mode == "get":
        local = pathlib.Path(args[2])
        fmt = "base64" if local.suffix in BINARY else "text"
        doc = api("GET", f"/api/contents/{args[1]}?content=1&type=file&format={fmt}")
        local.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "base64":
            local.write_bytes(base64.b64decode(doc["content"]))
        else:
            local.write_text(doc["content"])
        print("saved", local, local.stat().st_size, "bytes")
    elif mode == "ls":
        for item in api("GET", f"/api/contents/{args[1]}?content=1")["content"]:
            print(f"{item['type']:9s} {item.get('size') or '':>12} {item['name']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Small client for the Lambda Cloud API (https://cloud.lambda.ai/api/v1).

Reads the API key from LAMBDA_API_KEY. Never prints tokens.

  lambda_api.py types                      instance types with capacity, price and regions
  lambda_api.py instances                  running instances
  lambda_api.py ssh-keys                   SSH key names registered on the account
  lambda_api.py launch --type T --region R --ssh-key K [--name N] [--quantity 1]
  lambda_api.py wait --id ID [--save-url FILE] [--timeout 900]
  lambda_api.py terminate --id ID [--id ID ...]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://cloud.lambda.ai/api/v1"


def api(method, path, body=None):
    key = os.environ.get("LAMBDA_API_KEY")
    if not key:
        sys.exit("LAMBDA_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, method=method, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        sys.exit(f"HTTP {e.code} from {path}: {detail}")


def cmd_types(_):
    rows = []
    for name, v in api("GET", "/instance-types")["data"].items():
        regions = [r["name"] for r in v.get("regions_with_capacity_available", [])]
        if regions:
            t = v["instance_type"]
            rows.append((t["price_cents_per_hour"] / 100, name, t["description"], regions))
    for price, name, desc, regions in sorted(rows):
        print(f"${price:6.2f}/h  {name:24s} {desc:36s} {', '.join(regions)}")
    if not rows:
        print("no instance type has capacity right now")


def describe(i):
    t = i.get("instance_type", {})
    return (f"{i['id']}  {t.get('name')}  {i.get('status')}  {i.get('region', {}).get('name')}  "
            f"ip={i.get('ip')}  ${t.get('price_cents_per_hour', 0) / 100:.2f}/h  "
            f"ssh_keys={i.get('ssh_key_names')}  jupyter={'yes' if i.get('jupyter_url') else 'no'}")


def cmd_instances(_):
    data = api("GET", "/instances")["data"]
    print(f"{len(data)} instance(s)")
    for i in data:
        print(" ", describe(i))


def cmd_ssh_keys(_):
    for k in api("GET", "/ssh-keys")["data"]:
        print(k["name"])


def cmd_launch(a):
    body = {"region_name": a.region, "instance_type_name": a.type,
            "ssh_key_names": [a.ssh_key], "quantity": a.quantity}
    if a.name:
        body["name"] = a.name
    ids = api("POST", "/instance-operations/launch", body)["data"]["instance_ids"]
    print("launched", " ".join(ids))


def cmd_wait(a):
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        i = api("GET", f"/instances/{a.id}")["data"]
        url = i.get("jupyter_url") or ""
        if i.get("status") == "active" and url:
            if a.save_url:
                fd = os.open(a.save_url, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                os.write(fd, url.encode())
                os.close(fd)
                print("jupyter url saved to", a.save_url)
            print("active", describe(i))
            return
        print("waiting:", i.get("status"), flush=True)
        time.sleep(15)
    sys.exit("timed out waiting for the instance to become active")


def cmd_terminate(a):
    out = api("POST", "/instance-operations/terminate", {"instance_ids": a.id})["data"]
    for i in out.get("terminated_instances", []):
        print("terminating", i["id"], i.get("instance_type", {}).get("name"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("types").set_defaults(fn=cmd_types)
    sub.add_parser("instances").set_defaults(fn=cmd_instances)
    sub.add_parser("ssh-keys").set_defaults(fn=cmd_ssh_keys)
    s = sub.add_parser("launch")
    s.add_argument("--type", required=True)
    s.add_argument("--region", required=True)
    s.add_argument("--ssh-key", required=True)
    s.add_argument("--name")
    s.add_argument("--quantity", type=int, default=1)
    s.set_defaults(fn=cmd_launch)
    s = sub.add_parser("wait")
    s.add_argument("--id", required=True)
    s.add_argument("--save-url")
    s.add_argument("--timeout", type=int, default=900)
    s.set_defaults(fn=cmd_wait)
    s = sub.add_parser("terminate")
    s.add_argument("--id", action="append", required=True)
    s.set_defaults(fn=cmd_terminate)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Ensure the paperspace-runner notebook exists and is running.

Same path as the ComfyUI autostart: find by name -> start -> wait for Running.
Uses the console JWT in ~/.paperspace/jwt_token (paperspace_api.py).

Usage:
  python launch.py            # ensure running, print URL
  python launch.py --status   # print state only
  python launch.py --stop     # shut it down
"""
from __future__ import annotations

import argparse
import time

import paperspace_api as ps

NAME = "paperspace-runner"
PROJECT_ID = "pczh3y9dhu3"
MACHINE = "Free-A4000"
CONTAINER = "paperspace/gradient-base:pt211-tf215-cudatk120-py311-20240202"
WORKSPACE = "https://github.com/simonelmundo/paperspace-runner.git"
REF = "main"
COMMAND = (
    "bash entry.sh > /tmp/entry.log 2>&1 & "
    "jupyter lab --allow-root --ip=0.0.0.0 --no-browser"
)

STARTABLE = ("Off", "Stopped", "Suspended")
DEAD = ("Cancelled", "Canceled", "Failed", "Error", "Preempted")
ALIVE = ("Running", "Provisioned", "Starting", "Pending", "Stopping")


def find():
    return next((n for n in ps.list_notebooks() if n.name == NAME), None)


def create() -> str:
    return ps.create_notebook(
        name=NAME,
        project_id=PROJECT_ID,
        container=CONTAINER,
        machine_type=MACHINE,
        shutdown_timeout=6,
        workspace=WORKSPACE,
        workspace_ref=REF,
        command=COMMAND,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--stop-all", action="store_true", help="free tier allows one running notebook")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    try:
        nb = find()

        if args.status:
            print(f"{nb.name}: {nb.state}" if nb else f"{NAME}: not found")
            return 0

        if args.stop_all:
            for n in ps.list_notebooks():
                if n.state in ALIVE:
                    ps.stop_notebook(n.id)
                    print(f"stopping {n.id} ({n.name})")
            return 0

        if args.stop:
            if nb is None:
                print("not found")
            elif nb.state in ALIVE:
                ps.stop_notebook(nb.id)
                print(f"stopping {nb.id}")
            else:
                print(f"already {nb.state}")
            return 0

        if nb is None:
            nid = create()
            print(f"created {nid}")
        elif nb.state in DEAD:
            ps.delete_notebook(nb.id)
            nid = create()
            print(f"recreated {nid} (was {nb.state})")
        elif nb.state in STARTABLE:
            nid = ps.start_notebook(nb.id, MACHINE, 6)
            print(f"started {nid} (was {nb.state})")
        else:
            nid = nb.id
            print(f"{nid} already {nb.state}")

        deadline = time.time() + args.timeout
        last = None
        while time.time() < deadline:
            nb = next((n for n in ps.list_notebooks() if n.id == nid), None)
            state = nb.state if nb else "?"
            if state != last:
                print(f"  {state}")
                last = state
            if state == "Running":
                print(f"https://{nb.id}.{nb.cluster_id}.paperspacegradient.com?token={nb.token}")
                return 0
            if state in DEAD:
                print(f"failed: {state} {(nb.job_error or '').strip()}")
                return 1
            time.sleep(10)
        print("timed out waiting for Running")
        return 1
    except ps.SessionTokenExpiredError as exc:
        print(f"JWT expired: {exc}")
        print("Paste a fresh accessToken into ~/.paperspace/jwt_token")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

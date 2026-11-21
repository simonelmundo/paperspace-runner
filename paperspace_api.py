"""Legacy api.paperspace.io v2 calls using console session token (jwt)."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

import requests

logger = logging.getLogger(__name__)

LEGACY_BASE = "https://api.paperspace.io"
NAMESPACE = os.environ.get("PAPERSPACE_NAMESPACE", "ayayay")
CONSOLE_NOTEBOOKS_URL = os.environ.get(
    "PAPERSPACE_CONSOLE_NOTEBOOKS_URL",
    "https://console.paperspace.com/ayayay/projects/pczh3y9dhu3/notebooks",
)
# DigitalOcean new API (api.paperspace.com/v1). Auth = Bearer PAT, no console
# JWT involved. Legacy endpoints are deprecated by DO; v1 is the keep-alive
# path when they are switched off. Notebooks endpoints live on both APIs.
V1_BASE = "https://api.paperspace.com/v1"
# Flip with env: PAPERSPACE_USE_V1=1 (auto-fallback to v1 on legacy auth errors).
USE_V1 = os.environ.get("PAPERSPACE_USE_V1", "").strip() == "1"
# Single source of truth for the console session JWT (cookie accessToken).
# Optional override: PAPERSPACE_ACCESS_TOKEN env, or PAPERSPACE_JWT_FILE path.
TOKEN_FILE = Path(
    os.environ.get(
        "PAPERSPACE_JWT_FILE",
        str(Path.home() / ".paperspace" / "jwt_token"),
    )
)


class SessionTokenExpiredError(RuntimeError):
    """Raised when the console jwt is missing or rejected (HTTP 401)."""


def get_session_token() -> str:
    """Load JWT from env override or ~/.paperspace/jwt_token (re-read each call)."""
    env = os.environ.get("PAPERSPACE_ACCESS_TOKEN", "").strip()
    if env:
        return env
    if TOKEN_FILE.is_file():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise SessionTokenExpiredError(
        f"No Paperspace JWT at {TOKEN_FILE}. "
        "Paste a new jwt from the Paperspace console."
    )


def set_session_token(token: str) -> None:
    token = (token or "").strip()
    if not token:
        raise ValueError("JWT token cannot be empty")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    logger.info("Paperspace session token updated (%s)", TOKEN_FILE)


def open_console_notebooks() -> None:
    import webbrowser

    webbrowser.open(CONSOLE_NOTEBOOKS_URL)


def should_fallback(exc: Exception) -> bool:
    if isinstance(exc, SessionTokenExpiredError):
        return True
    msg = str(exc).lower()
    return any(
        x in msg
        for x in (
            "401",
            "access token",
            "authorization required",
            "failed to fetch data",
            "failed to create resource",
            "failed to delete",
            "no access token",
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": get_session_token(),
        "x-client": "PS_WEB",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _raise_if_bad(response: requests.Response, action: str) -> None:
    if response.status_code == 401:
        raise SessionTokenExpiredError(
            f"Session token expired or invalid during {action}. "
            "Paste a new jwt from the Paperspace console."
        )
    if response.status_code < 400:
        return
    text = (response.text or "")[:500]
    raise RuntimeError(f"Session fallback {action} failed ({response.status_code}): {text}")


def list_notebooks(limit: int = 100) -> list[SimpleNamespace]:
    filt = json.dumps(
        {
            "filter": {
                "limit": limit,
                "where": {"dtDeleted": None},
                "order": "jobId desc",
            }
        }
    )
    r = requests.get(
        f"{LEGACY_BASE}/notebooks/getNotebooks",
        headers=_headers(),
        params={"namespace": NAMESPACE, "filter": filt},
        timeout=60,
    )
    _raise_if_bad(r, "list")
    out = []
    for item in r.json().get("notebookList", []):
        out.append(
            SimpleNamespace(
                id=item.get("handle"),
                state=item.get("state"),
                project_handle=item.get("projectHandle"),
                project=item.get("project"),
                name=item.get("name"),
                # Paperspace console Logs stay empty when the pod never becomes ready;
                # jobError is the real failure reason from the control plane.
                job_error=item.get("jobError") or item.get("job_error"),
                machine_type=item.get("vmType") or item.get("machineType"),
                token=item.get("token"),
                cluster_id=item.get("clusterId") or "clg07azjl",
            )
        )
    return out


def delete_notebook(notebook_id: str) -> None:
    r = requests.post(
        f"{LEGACY_BASE}/notebooks/v2/deleteNotebook",
        headers={k: v for k, v in _headers().items() if k != "Content-Type"},
        params={"notebookId": notebook_id, "namespace": NAMESPACE},
        timeout=60,
    )
    _raise_if_bad(r, "delete")
    logger.info("Session fallback deleted notebook %s", notebook_id)


def stop_notebook(notebook_id: str) -> None:
    r = requests.post(
        f"{LEGACY_BASE}/notebooks/v2/stopNotebook",
        headers=_headers(),
        params={"namespace": NAMESPACE},
        json={"notebookId": notebook_id},
        timeout=60,
    )
    _raise_if_bad(r, "stop")


def start_notebook(notebook_id: str, machine_type: str, shutdown_timeout: int = 6) -> str:
    body = {
        "notebookId": notebook_id,
        "machineType": machine_type,
        "shutdownTimeout": int(shutdown_timeout),
    }
    r = requests.post(
        f"{LEGACY_BASE}/notebooks/v2/startNotebook",
        headers=_headers(),
        params={"namespace": NAMESPACE},
        json=body,
        timeout=120,
    )
    _raise_if_bad(r, "start")
    data = r.json() if r.text else {}
    return data.get("handle") or notebook_id


DEFAULT_TOOLBOX_PROJECT_ID = "pczh3y9dhu3"


def get_or_create_project(name: str, api_key: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(
            "https://api.paperspace.com/v1/projects",
            headers=headers,
            timeout=30,
        )
        if r.ok:
            for project in r.json().get("items", []):
                if project.get("name") == name:
                    pid = project.get("id")
                    if pid:
                        return pid
    except Exception as e:
        logger.warning("v1 project list failed: %s", e)

    for nb in list_notebooks():
        if getattr(nb, "project", None) == name and nb.project_handle:
            return nb.project_handle

    if "From Toolbox" in name:
        return DEFAULT_TOOLBOX_PROJECT_ID

    raise RuntimeError(f"Could not resolve project id for '{name}' (session/v1 fallback)")


# --- new DigitalOcean v1 API (Bearer PAT, no JWT) ---------------------------

class V1NotConfiguredError(RuntimeError):
    """Raised when no PAT is available for the new api.paperspace.com API."""


def get_api_key() -> str:
    """Load the Paperspace PAT for the new API from env (toolbox sets it)."""
    key = os.environ.get("PAPERSPACE_API_KEY", "").strip()
    if not key:
        raise V1NotConfiguredError(
            "No PAPERSPACE_API_KEY set. The v1 API needs PAT auth "
            "(Authorization: Bearer), not the console JWT."
        )
    return key


def _v1_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_api_key()}"}


def create_v1_notebook(**kwargs) -> str:
    """POST /v1/notebooks - notebooks are NOT documented in DO's api-reference,
    but the endpoint exists and shares the zod schema of legacy createNotebook."""
    from datetime import datetime

    body = {
        "projectId": kwargs.get("project_id"),
        "name": kwargs.get("name") or f"toolbox-{int(time.time())}",
        "machineType": kwargs.get("machine_type", "Free-A4000"),
        "shutdownTimeout": int(kwargs.get("shutdown_timeout") or 6),
        "command": kwargs.get("command", ""),
    }
    for k_src, k_dst in (
        ("container", "container"),
        ("workspace", "workspace"),
        ("workspace_ref", "workspaceRef"),
        ("workspace_username", "workspaceUsername"),
        ("workspace_password", "workspacePassword"),
        ("registry_username", "registryUsername"),
        ("registry_password", "registryPassword"),
    ):
        if kwargs.get(k_src):
            body[k_dst] = kwargs[k_src]
    if kwargs.get("environment"):
        body["environment"] = kwargs["environment"]

    r = requests.post(f"{V1_BASE}/notebooks", headers=_v1_headers(), json=body, timeout=120)
    _raise_if_bad_v1(r, "create")
    data = r.json() if r.text else {}
    handle = data.get("id") or data.get("handle")
    if not handle:
        raise RuntimeError(f"v1 create missing handle: {json.dumps(data)[:200]}")
    logger.info("v1 API created notebook %s (%s)", handle, datetime.now().isoformat(timespec="seconds"))
    return handle


def _raise_if_bad_v1(r: requests.Response, action: str) -> None:
    if r.status_code < 400:
        return
    text = (r.text or "")[:300]
    raise RuntimeError(f"v1 API {action} failed ({r.status_code}): {text}")


def list_v1_notebooks(limit: int = 100) -> list[dict]:
    r = requests.get(f"{V1_BASE}/notebooks", headers=_v1_headers(), params={"limit": limit}, timeout=60)
    _raise_if_bad_v1(r, "list")
    if r.status_code >= 400:
        raise RuntimeError(f"v1 API list failed ({r.status_code}): {(r.text or '')[:300]}")
    data = r.json() if r.text else {}
    return data.get("items") or data.get("notebookList") or []


def delete_v1_notebook(notebook_id: str) -> None:
    r = requests.delete(f"{V1_BASE}/notebooks/{notebook_id}", headers=_v1_headers(), timeout=60)
    if r.status_code < 400:
        logger.info("v1 API deleted notebook %s", notebook_id)
        return
    raise RuntimeError(f"v1 API delete failed ({r.status_code}): {(r.text or '')[:300]}")


def stop_v1_notebook(notebook_id: str) -> None:
    r = requests.post(f"{V1_BASE}/notebooks/{notebook_id}/stop", headers=_v1_headers(), json={}, timeout=60)
    if r.status_code < 400:
        return
    raise RuntimeError(f"v1 API stop failed ({r.status_code}): {(r.text or '')[:300]}")


def create_notebook(**kwargs) -> str:
    cmd = kwargs.get("command") or ""
    if cmd and not str(cmd).strip().startswith("echo "):
        try:
            base64.b64decode(cmd, validate=True)
            cmd_b64 = cmd
        except Exception:
            cmd_b64 = base64.b64encode(str(cmd).encode()).decode()
    else:
        cmd_b64 = cmd

    body = {
        "name": kwargs.get("name") or f"toolbox-{int(time.time())}",
        "projectId": kwargs.get("project_id"),
        "container": kwargs.get("container"),
        "machineType": kwargs.get("machine_type", "Free-A4000"),
        "shutdownTimeout": int(kwargs.get("shutdown_timeout") or 6),
        "workspace": kwargs.get("workspace") or "",
        "workspaceRef": kwargs.get("workspace_ref") or "",
        "workspaceUsername": kwargs.get("workspace_username") or "",
        "workspacePassword": kwargs.get("workspace_password") or "",
        "registryUsername": kwargs.get("registry_username") or "",
        "registryPassword": kwargs.get("registry_password") or "",
        "command": cmd_b64,
    }
    if kwargs.get("environment"):
        body["environment"] = kwargs["environment"]

    r = requests.post(
        f"{LEGACY_BASE}/notebooks/v2/createNotebook",
        headers=_headers(),
        params={"namespace": NAMESPACE},
        json=body,
        timeout=120,
    )
    _raise_if_bad(r, "create")
    data = r.json()
    handle = data.get("handle")
    if not handle:
        raise RuntimeError(f"Session fallback create missing handle: {data}")
    logger.info("Session fallback created notebook %s", handle)
    return handle

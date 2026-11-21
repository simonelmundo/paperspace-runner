#!/usr/bin/env bash
# Minimal Paperspace bootstrap. No ComfyUI, no model downloads, no pip installs.
# /notebooks survives restarts; / and /tmp are wiped on every boot.
set -uo pipefail

ROOT=/notebooks
mkdir -p "$ROOT/work" "$ROOT/logs" "$ROOT/.envs" "$ROOT/cache"

# uv: per-project venvs without root or conda
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:$PATH"
fi

# What the stack actually is, so a boot can be verified without opening a terminal.
{
  echo "ready $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "python $(python -V 2>&1)"
  echo "uv $(uv --version 2>/dev/null || echo missing)"
  echo "ffmpeg $(ffmpeg -version 2>/dev/null | head -n1)"
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1
} > "$ROOT/READY"

echo "[entry] done -> /notebooks/READY"

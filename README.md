# paperspace-runner

Minimal Paperspace notebook workspace. Boots in seconds instead of minutes: no ComfyUI,
no model downloads, no pip installs. Just the persistent directories, `uv`, and a
`/notebooks/READY` file describing the stack.

## Launch config (Paperspace console -> Launch a notebook)

| Field | Value |
|---|---|
| Template | Start from Scratch |
| Machine | **Free-A4000** (16 GB, Ampere) - not P5000, see below |
| Auto-shutdown | 6 Hours |
| Workspace URL | `https://github.com/simonelmundo/paperspace-runner.git` |
| Ref | `main` |
| Container | `paperspace/gradient-base:pt211-tf215-cudatk120-py311-20240202` |
| Command | `bash entry.sh > /tmp/entry.log 2>&1 & jupyter lab --allow-root --ip=0.0.0.0 --no-browser` |

Keep the `jupyter lab` part: it is the transport the MCP uses to run commands.
`entry.sh` runs in the background so Jupyter starts immediately.

## Verify a boot

Read `/notebooks/READY` on the box (MCP: `paperspace_read_file`). It should show
python 3.11, uv, ffmpeg and the GPU line. If it is missing, check `/tmp/entry.log`.

## Layout on the box

```
/notebooks/work/<job>/      job inputs and outputs   persists
/notebooks/logs/<job>.log   job logs, polled for DONE persists
/notebooks/.envs/<hash>/    per-project venvs        persists
/notebooks/cache/           model and package cache  persists
/tmp/                       anything                 wiped every boot
```

## Why A4000 and not P5000

Both have 16 GB. P5000 is Pascal: no Tensor Cores and poor fp16 throughput, which
makes faster-whisper noticeably slower. On P5000, set `WHISPER_COMPUTE=int8`
(no float16). On A4000, `float16` with a larger batch.

# Gotchas, each learned the hard way

## Access

- The user's `~/.ssh/<key-name>` may be the **public** key only (105 bytes, starts with
  `ssh-ed25519`). `ssh-keygen -y -P "" -f` on it prints "invalid format". Check before planning
  around SSH; fall back to the Jupyter endpoint, which every Lambda instance exposes.
- The Jupyter proxy returns HTTP 403 to Python's default `urllib` User-Agent on POST. Send a
  curl-style User-Agent on every request, including the websocket upgrade.
- Token auth goes in the `Authorization: token ...` header, never in a query string you log.
- A kernel executes one request at a time. A long `sh` wait loop blocks every later `sh`, `bg`
  and `put` until it finishes; put waits in detached `bg` scripts or in a second kernel, and
  use the contents API (`putc`, `get`, `ls`) for file transfer, which needs no kernel.

## Instances

- Boot takes 3 to 10 minutes; H100s in some regions take longer than A100s. Poll with
  `wait`, do local preparation meanwhile.
- `instance-types` lists every type; only those with `regions_with_capacity_available` can be
  launched. Prices are in cents per hour.
- `terminate` returns while the instance still shows `terminating`; it disappears from the list
  a minute or two later. Confirm zero instances before saying billing has stopped.
- Lambda Stack images ship torch with CUDA for the system Python; pip may complain about
  unrelated pinned packages (virtualenv, pipx). Those warnings are harmless.
- `pip install` on Ubuntu 24.04 images may need `--break-system-packages`.

## Runs

- Two runs downloading and extracting the same dataset archive at once corrupt it; download
  once first.
- Logs written by `torchvision` downloads contain hundreds of progress lines; readers must
  ignore anything that is not the header, a JSON line, `FINAL` or `STOPPED`.
- Training with `label_smoothing=0.1` floors the loss near 0.5; that is not a bug.
- `OneCycleLR` cycles momentum (0.95 to 0.85) by default; do not describe the run as
  "momentum 0.9".
- A run that is killed loses everything not yet written; metrics only exist for runs that reach
  `FINAL`. If the user may stop early, log validation every epoch so a stopped run still has a
  partial story.
- Keep the weights transfer under about 1 GB per file when using the contents API (base64 in
  memory on both ends); larger checkpoints need SSH/scp or object storage.

## Money and secrets

- Say the hourly price every time before launching, and remind the user that both the old and
  the new instance bill when a second one is added.
- Never echo the API key in a command description, a log, a dashboard folder or a commit.
  Store it in a 0600 file outside the repo if it must be on disk, and truncate that file at
  teardown (`: > file`), never `rm`.
- If the key was pasted into chat, it is in the transcript: tell the user to rotate it.

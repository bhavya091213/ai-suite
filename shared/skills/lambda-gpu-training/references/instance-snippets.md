# Commands that run on the instance

All of these are run through `jupyter_exec.py sh` or `bg` (or over SSH when a key works).
`PYTHON` is replaced by the kernel's interpreter, which is the one with torch preinstalled.

## Checks

```sh
nvidia-smi --query-gpu=name,memory.total,utilization.gpu,memory.used --format=csv,noheader
PYTHON -c "import torch, torchvision; print(torch.__version__, torchvision.__version__, torch.cuda.is_available())"
df -h ~ | tail -1; nproc
```

## Extra packages

```sh
PYTHON -m pip install -q --user timm > pip.log 2>&1 || PYTHON -m pip install -q --user --break-system-packages timm >> pip.log 2>&1
```

## Dataset once, then parallel runs

Download in one process first (or make the first run download and have the others wait for
its `device=` header line before starting):

```sh
cd ~/project && PYTHON -c "import torchvision; torchvision.datasets.CIFAR10('data', download=True); torchvision.datasets.CIFAR10('data', train=False, download=True)"
```

## Start a run detached (use `bg` mode; this is what it does)

```sh
cd ~/project && PYTHON -u train.py --mode scratch --epochs 200 --out artifacts/run_a   # log: ~/project/dash/run_a.log
```

## Live dashboard: local server plus Cloudflare quick tunnel

Serve only the `dash/` folder, bound to localhost; the tunnel exposes it. Lambda images already
run a system `cloudflared` with `/etc/cloudflared/config.yml` for the Jupyter endpoint, and a
quick tunnel started without its own config picks that file up and answers 404 for everything,
so always pass an empty config file.

```sh
cd ~/project/dash && PYTHON -m http.server 8080 --bind 127.0.0.1          # bg mode, log ~/project/http.log
mkdir -p ~/project/bin && cd ~/project/bin && (test -x cloudflared || (curl -sL -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x cloudflared)) && : > quick.yml && ./cloudflared --config ~/project/bin/quick.yml tunnel --no-autoupdate --url http://127.0.0.1:8080   # bg mode, log ~/project/tunnel.log
grep -o "https://[a-z0-9-]*\.trycloudflare\.com" ~/project/tunnel.log | head -1
```

Tell the user the URL is public but unguessable and dies with the instance.

## Wait for runs and publish their metrics (detached)

```sh
cd ~/project && for i in $(seq 700); do [ "$(cat dash/a.log dash/b.log | grep -c '^FINAL')" -eq 2 ] && break; sleep 5; done; cp artifacts/a/metrics.json dash/a.metrics.json; cp artifacts/b/metrics.json dash/b.metrics.json
```

## Stop things

`pkill -f` matches the shell that runs it when the pattern appears in that shell's command
line; the bracket form avoids that.

```sh
pkill -f "[t]rain.py --mode"                                   # training runs
pkill -f "[q]uick.yml tunnel"                                   # only your tunnel, never the system one
pkill -f "[h]ttp.server 8080"
pgrep -af "[t]rain.py" | wc -l                                 # should print 0
```

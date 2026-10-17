---
name: lambda-gpu-training
description: Phased workflow for training or fine-tuning ML models on rented Lambda cloud GPUs. Interviews the user about goal, constraints, budget and deliverables, then handles instance access (SSH, or the Jupyter endpoint when the private key is missing), environment setup, background runs with live logs, progress summaries, collection of weights and metrics, instance teardown and a results report. Use when the user mentions Lambda, lambda.ai, renting a GPU, an A100/H100 instance, or wants to train a model on cloud compute.
origin: local
---

# Lambda GPU training

Run a training project on Lambda cloud GPUs in phases, each ending with a short summary to the
user and, where money or evaluation integrity is at stake, an explicit gate. The user owns the
decisions that cost money (launching, keeping, terminating instances) and the decisions that
define the result (what counts as the headline number). You own everything else.

Three rules that never bend:

1. **Money gates.** Never launch, resize or terminate an instance the user did not ask for. Quote
   the hourly price before launching. Every running instance bills until terminated, so the end of
   the job is not done until the account lists zero instances the user wants gone.
2. **Evaluation hygiene.** Hold out a validation split from the training data, fix it with a seed,
   select everything on it, and evaluate the test set once per run after training. Never pick
   between runs by their test numbers; report all of them.
3. **Secrets.** The API key lives in `LAMBDA_API_KEY` (environment or keychain), never in chat,
   files in a repo, logs or command descriptions. If the user pastes a key into chat, use it,
   and tell them once to rotate it afterwards.

Helper scripts live beside this file: `scripts/lambda_api.py` (instance types, launch, wait,
terminate) and `scripts/jupyter_exec.py` (run commands and move files through an instance's
Jupyter endpoint). Both read their credentials from the environment. See
`references/run-conventions.md` for the log and metrics format every training script should
follow, `references/instance-snippets.md` for commands that run on the instance, and
`references/gotchas.md` before touching anything.

## Phases

| Phase | Output | Gate |
| --- | --- | --- |
| 0 Intake and plan | Written plan with runs, cost estimate, ETA | User approves the plan |
| 1 Access | Reachable instance, access method known | User confirms price before any launch |
| 2 Environment | Dependencies, data, code and smoke test on the instance | none |
| 3 Launch | Runs started in the background, ledger written | none |
| 4 Monitor | Progress summaries at milestones, optional live dashboard | User decides on extra experiments |
| 5 Collect | Metrics, logs and weights on the local machine | none |
| 6 Teardown | Zero instances, tunnels and servers killed, secrets blanked | User asks for termination |
| 7 Report | Results table with caveats, deliverables | none |

Keep a run-state file (for example `.lambda-run/<slug>.md`, ignored by git) with the plan, the
instance ids, the run ledger and the collection checklist, and update it as you go. After a
context compaction, re-read it instead of re-deriving.

## Phase 0: intake and plan

Ask before building. Use `AskUserQuestion` for bounded choices and plain questions otherwise;
one or two rounds is usually enough. Cover:

- **Task and data**: dataset, where it comes from, size, and the metric that matters.
- **Goal**: highest accuracy, a quick baseline, reproduce a paper, or a specific target number.
- **Rules**: pretrained weights allowed or from scratch only; augmentation and regularisation
  allowed; anything the course, paper or client forbids.
- **Budget**: wall-clock time available, and money. Turn both into a GPU choice later.
- **Deliverables**: weights, metrics, scripts, README, written report (LaTeX or Markdown), live
  dashboard, an explanation the user has to present.
- **Compute**: an instance already running, or launch one; preferred GPU; whether the private
  SSH key for their Lambda key pair is on this machine.
- **Evaluation**: confirm the held-out validation split and single test evaluation; ask how many
  seeds they want behind the headline number.

Then run the local pre-flight (Python, package manager, GPU-free dry run of the data loader) and
write the plan: the runs with their settings, the GPU and its price, the estimated cost
(`price x hours`, rounded up), the ETA, what will be delivered, and the evaluation rules.
Present it and stop until the user says go. If they give a hard deadline, cut the plan to fit it
and say what was cut.

## Phase 1: access

1. Credentials: `export LAMBDA_API_KEY=...` in the user's shell, or
   `export LAMBDA_API_KEY=$(security find-generic-password -s lambda-api-key -w)` on macOS.
   Confirm it works with `python3 scripts/lambda_api.py instances`.
2. Existing instance: `instances` prints id, type, status, region, ssh key names and whether a
   Jupyter URL exists. New instance: `types` prints only types with capacity, with price per hour
   and regions; present the sensible options with prices, let the user pick, then
   `launch --type ... --region ... --ssh-key ...` and `wait --id ... --save-url <0600 file>`.
   Booting takes 3 to 10 minutes; use the time for Phase 2 preparation locally.
3. Access method, in order:
   - **SSH** if `ssh-keygen -y -P "" -f ~/.ssh/<key>` reproduces the public key the instance was
     launched with. Use `ssh -o BatchMode=yes` so a missing key fails fast instead of prompting.
   - **Jupyter endpoint** otherwise. Every Lambda instance exposes one; `wait --save-url` stores
     its URL (token included) in a file with mode 0600. Run everything through
     `scripts/jupyter_exec.py` with `JUPYTER_URL_FILE=<that file>`.
   - Do not add SSH keys to the instance or the account on your own; that is an account change.
4. Summarise: instance type, region, hourly price, access method, what is on it (GPU, torch
   version, disk).

## Phase 2: environment

- Check `nvidia-smi`, `python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"`,
  free disk, and which Python the Jupyter kernel uses (`sys.executable`); use that interpreter
  for training so the preinstalled torch is found.
- Install extras with `pip install --user <pkg>`; on newer Ubuntu images fall back to
  `--break-system-packages`. Keep pip output out of the training logs.
- Upload the training script with `put`. Download the dataset **once, in a single process**,
  before starting anything in parallel; two processes extracting the same archive corrupt it.
- Smoke test the exact command on a tiny subset locally first, then on the instance, and check
  the run writes its metrics file at the end. A bug in the final save loses the whole run.
- Summarise what is installed and confirmed.

## Phase 3: launch

- Start each run detached (`bg` mode: `Popen` with a new session, stdout and stderr to
  `<project>/dash/<run>.log`), never in the foreground of a kernel call.
- Name runs by what they are (`resnet18_cutout_200ep`), write each run's full command into the
  ledger, and give every run the same validation split.
- One GPU shared by N runs makes each about N times slower; three or four concurrent runs on one
  A100 is a practical ceiling. Measure the first epoch and compute the ETA from it; the first
  epoch includes compile and warm-up, so re-check after two.
- A second instance only helps if there is independent work for it; its boot time and price
  go in the plan.
- Summarise: what is running where, ETA per run, total expected cost.

## Phase 4: monitor

- Poll logs with `get` (or `curl` against the dashboard) every few minutes while runs are young,
  then at milestones. Report to the user at: first-epoch ETA, roughly half way, each completion,
  and any error. One line per run: epoch, latest validation accuracy, elapsed.
- Live dashboard, if the user wants one: on the instance, serve only the `dash/` folder with
  `python3 -m http.server --bind 127.0.0.1 <port>` and expose it with a Cloudflare quick tunnel
  started with its **own empty config file** (`references/instance-snippets.md`). The URL is
  public but unguessable; say so, and never put secrets in that folder.
- New experiments mid-flight (more seeds, a wider model, a bigger pretrained backbone) are the
  user's call: give the expected gain, the time and the cost, then wait for a yes.
- When told to stop, kill the training processes with the `[t]rain.py` bracket pattern so the
  shell running `pkill` does not match itself, and record the epoch each run reached.

## Phase 5: collect

Do this before any termination, and verify sizes after each transfer:

- `metrics.json` for every finished run; logs for every run (filter to the header, JSON and
  `FINAL` lines; append `STOPPED` to logs of runs that were stopped early).
- Weights for the runs the user wants; the Jupyter contents API moves files of a few hundred MB
  as base64, so a 1 GB checkpoint is the practical limit per transfer.
- Anything a report or dashboard needs offline, copied next to it.
- Tick the checklist in the run-state file.

## Phase 6: teardown

1. Kill training processes, your own `cloudflared` quick tunnel (not the system one in
   `/etc/cloudflared`, which serves the Jupyter endpoint you are using) and any local web server.
2. Terminate the instance(s) with `terminate --id ...` only after the user asked for it, then
   poll `instances` until the account lists zero of them and tell the user.
3. Blank (truncate, never delete) any local file holding a token or key; rotate anything that was
   exposed in chat. Confirm `.gitignore` covers `.env*`, key files, weights and the dataset.
4. Summarise what was stopped, what was saved, and the final cost estimate.

## Phase 7: report

A results table with validation and test for every run; how many seeds each number rests on;
runs that were stopped early in their own table; the validation-versus-test gap and what it
means; the cost and time actually used; what was cut and why. Then the deliverables the user
chose. Finish with the handback: files, how to reproduce, and open follow-ups.

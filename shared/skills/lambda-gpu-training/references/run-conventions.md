# Run conventions

Every training script launched through this skill should follow these conventions so logs,
dashboards, reports and re-evaluation all work without per-run special cases.

## Log format (stdout, unbuffered: `python3 -u`)

```
device=cuda mode=scratch params=11.17M train=48000 val=2000 steps/epoch=187
{"step": 25, "total_steps": 5610, "loss": 1.84, "elapsed_s": 4.1}
{"epoch": 1, "train_loss": 1.57, "train_acc": 0.5047, "val_acc": 0.5995, "elapsed_s": 3.4}
...
FINAL test_acc=0.9450 val_acc=0.9480 time=145.8s
```

- One header line starting with `device=`, then one JSON object per logged step and per epoch,
  then one `FINAL` line. Anything else (download progress, warnings) is ignored by readers.
- A run stopped before finishing gets a line `STOPPED` appended by whoever stopped it.
- Logs go to `<project>/dash/<run>.log` on the instance; the same folder can be served as a
  live dashboard, so never write secrets or absolute user paths into it.

## metrics.json (written once, at the end, next to the weights)

```json
{
  "test_acc": 0.9450,
  "val_acc": 0.9480,
  "val_idx_sum": 50129101,
  "per_class_test_acc": {"airplane": 0.951, "...": 0.0},
  "params": 11173962,
  "train_seconds": 145.8,
  "device": "cuda",
  "config": {"mode": "scratch", "epochs": 30, "bs": 256, "lr": 0.2, "seed": 0, "split_seed": 0},
  "history": [{"epoch": 1, "train_loss": 1.57, "train_acc": 0.50, "val_acc": 0.60, "elapsed_s": 3.4}]
}
```

- `config` is the full set of command-line arguments, so a run can be reproduced and a report
  script can check that a run matches the recipe it is labelled with.
- Record something that identifies the validation split (index sum or a hash of the ordered
  indices) so a later evaluation can prove it used the same held-out images.
- Save weights with `torch.save(model.state_dict(), ...)` only after the metrics file is written;
  a crash in the final save must not lose the numbers.

## Evaluation hygiene

- Split: `torch.randperm(n, generator=torch.Generator().manual_seed(split_seed))`; the split
  seed is separate from the training seed so different seeds share the same validation set.
- No early stopping or best-checkpoint selection unless the user asks; evaluate the final
  weights. Test-time augmentation (for example flip averaging) is decided before the run.
- The test set is evaluated once per run, after training. Choosing between runs uses validation
  accuracy only. Report every run's test number, including the losers.
- Expect validation to differ from test by a few tenths of a point in either direction; with
  2,000 validation images the 95% interval at 96% accuracy is about +/-0.9 points, so small
  differences between single runs are noise. Repeat the headline recipe over seeds when the
  user wants a number they can defend.

## Throughput planning

- Keep the whole dataset on the GPU as uint8 and augment on the GPU when it fits (CIFAR-size
  data does); a `DataLoader` with workers is then unnecessary.
- Use bfloat16 autocast on Ampere or newer; `channels_last`; `cudnn.benchmark = True`.
- Measure the first two epochs, then compute ETA; N concurrent runs on one GPU each run about
  N times slower.

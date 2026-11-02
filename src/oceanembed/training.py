"""Single-GPU/CPU training with validation selection and resumable checkpoints."""

import json
import random
import shutil
import time
from pathlib import Path
import numpy as np
import torch
import xarray as xr
from torch.utils.data import DataLoader
from .contracts import load_cube, dump, sha256
from .dataset import Windows, split_indices, fit_transforms
from .model import OceanNet, masked_loss


def train(config, resume=None):
    cfg = config
    out = Path(cfg["output"])
    cube_hash = sha256(cfg["cube"])
    state = None
    if resume:
        if Path(resume).resolve().parent != out.resolve():
            raise ValueError("Resume from the same training directory to preserve best weights")
        state = torch.load(resume, map_location="cpu", weights_only=False)
        if state.get("training_schema") != 2 or state.get("cube_sha256") != cube_hash or state.get("config") != cfg:
            raise ValueError("Resume data/config/code schema differs; start a new versioned run")
    elif (out/"weights.pt").exists() or (out/"resume.pt").exists():
        raise ValueError("Training output exists: resume it or choose a new output directory")
    out.mkdir(parents=True, exist_ok=True)
    seed = cfg.get("seed", 42)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(cfg.get("cpu_threads", 2))
    ds = load_cube(cfg["cube"])
    splits = split_indices(ds, cfg)
    tr = fit_transforms(ds, cfg, out / "transforms.nc")
    dump(out / "config.json", cfg)
    source_manifest = Path(cfg["cube"]).with_suffix(".sources.json")
    if source_manifest.exists():
        shutil.copy2(source_manifest, out / "source_manifest.json")
    dump(
        out / "split_manifest.json",
        {k: [str(ds.time.values[i])[:10] for i in v] for k, v in splits.items()},
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = OceanNet(cfg["width"], cfg.get("temporal", True)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"])
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    first = 0
    best = float("inf")
    history = []
    if resume:
        # The trusted checkpoint was validated before any output files were written.
        if state["config"] != cfg:
            raise ValueError("Resume config differs; keep identical config")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scaler.load_state_dict(state["scaler"])
        first = state["epoch"] + 1
        best = state["best"]
        history = state["history"]
        torch.set_rng_state(state["rng"].cpu())
        np.random.set_state(state["numpy_rng"])
        random.setstate(state["python_rng"])
        if device.type == "cuda" and state.get("cuda_rng") is not None:
            torch.cuda.set_rng_state_all(state["cuda_rng"])
    loaders = {
        k: DataLoader(
            # Training crops vary across epochs for spatial coverage; validation
            # crops stay fixed so checkpoint selection compares like with like.
            Windows(ds, tr, splits[k], cfg, cfg.get("patch"), vary_crops=(k == "train")),
            batch_size=cfg["batch_size"],
            shuffle=k == "train",
            num_workers=0,
        )
        for k in ["train", "validation"]
    }
    for epoch in range(first, cfg["epochs"]):
        loaders["train"].dataset.set_epoch(epoch)
        before = time.time()
        stats = {}
        for phase, loader in loaders.items():
            model.train(phase == "train")
            total = 0.0
            n = 0
            for step, batch in enumerate(loader):
                if cfg.get("max_batches") and step >= cfg["max_batches"]:
                    break
                x, p, s, y = [v.to(device, dtype=torch.float32) for v in batch]
                if not torch.isfinite(y).any():
                    continue
                optimizer.zero_grad(set_to_none=True)
                with torch.set_grad_enabled(phase == "train"):
                    with torch.autocast(
                        device_type=device.type, enabled=device.type == "cuda"
                    ):
                        pred = model(x, p, s)
                        loss = masked_loss(pred, y)
                    if not torch.isfinite(loss):
                        raise ValueError("Nonfinite training loss")
                    if phase == "train":
                        scaler.scale(loss).backward()
                        scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                        scaler.step(optimizer)
                        scaler.update()
                total += loss.item()
                n += 1
            if not n:
                raise ValueError(f"No supported batches in {phase}")
            stats[phase] = total / n
        improved = stats["validation"] < best
        best = min(best, stats["validation"])
        record = {"epoch": epoch, **stats, "seconds": time.time() - before}
        history.append(record)
        print(record, flush=True)
        checkpoint = {
            "training_schema": 2,
            "cube_sha256": cube_hash,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scaler": scaler.state_dict(),
            "epoch": epoch,
            "best": best,
            "config": cfg,
            "history": history,
            "rng": torch.get_rng_state(),
            "numpy_rng": np.random.get_state(),
            "python_rng": random.getstate(),
            "cuda_rng": (
                torch.cuda.get_rng_state_all() if device.type == "cuda" else None
            ),
        }
        tmp = out / "resume.tmp"
        torch.save(checkpoint, tmp)
        tmp.replace(out / "resume.pt")
        if improved:
            torch.save(model.state_dict(), out / "weights.pt")
        dump(out / "history.json", history)
    dump(
        out / "manifest.json",
        {
            "source_mode": ds.attrs["source_mode"],
            "cube_sha256": sha256(cfg["cube"]),
            "weights_sha256": sha256(out / "weights.pt"),
            "device": str(device),
            "scientific_validation": "pending",
            "training_reference": (
                "synthetic" if ds.attrs["source_mode"] == "synthetic" else "reanalysis"
            ),
            "model": "shared CNN + causal TCN + prior-conditioned direct head",
            "version": "0.5.0",
        },
    )
    return out


def load_model(bundle, device="cpu"):
    bundle = Path(bundle)
    cfg = json.loads((bundle / "config.json").read_text())
    if (bundle / "checksums.json").exists():
        for name, expected in json.loads(
            (bundle / "checksums.json").read_text()
        ).items():
            if Path(name).name != name or sha256(bundle / name) != expected:
                raise ValueError(f"Bundle checksum mismatch: {name}")
    model = OceanNet(cfg["width"], cfg.get("temporal", True)).to(device)
    model.load_state_dict(
        torch.load(bundle / "weights.pt", map_location=device, weights_only=True)
    )
    model.eval()
    with xr.open_dataset(bundle / "transforms.nc") as f:
        tr = f.load()
    return model, tr, cfg

"""Run the three CUDA reader experiments with explicit data provenance.

This is an offline experiment. Its validation scores do not enable a reader in
the live application; reviewed, independent game footage is still required.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def run(command: list[str], label: str, status_file: Path) -> bool:
    print(f"\n=== {label} ===", flush=True)
    print(" ".join(command), flush=True)
    status_file.write_text(json.dumps({"stage": label, "state": "running"}))
    result = subprocess.run(command, check=False)
    status_file.write_text(json.dumps({"stage": label, "state": "done" if result.returncode == 0 else "failed",
                                       "exit_code": result.returncode}))
    return result.returncode == 0


def wait_for_audit(path: Path, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        print("Aguardando extração dos dígitos do HUD...", flush=True)
        time.sleep(15)
    return path.exists()


def train(python: str, weights: Path, data: Path, project: Path, name: str,
          epochs: int, size: int, batch: int, status: Path) -> bool:
    yolo = str(Path(python).with_name("yolo"))
    common = [yolo, "classify", "train", f"model={weights}",
              f"data={data}", f"epochs={epochs}", f"imgsz={size}", "device=0",
              f"workers=4", f"project={project}", f"name={name}",
              "exist_ok=True", "plots=False", "patience=12", "amp=True"]
    for current_batch in (batch, max(8, batch // 2), 8):
        if run(common + [f"batch={current_batch}"], f"treino {name}, lote {current_batch}", status):
            return True
        print("Treino falhou; verificando lote menor.", flush=True)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--champions", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--digits", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    status = args.output / "status.json"
    failed = []
    experiments = (
        ("champion-names", args.champions, 50, 224, 32, "test"),
        ("item-art", args.items, 40, 96, 64, None),
        ("hud-digits", args.digits, 35, 64, 64, "test"),
    )
    for name, data, epochs, size, batch, test_split in experiments:
        if name == "hud-digits" and not wait_for_audit(data / "audit.json", 3600):
            failed.append(f"{name}: digit extraction timed out")
            continue
        if not (data / "train").is_dir() or not (data / "val").is_dir():
            failed.append(f"{name}: missing train/val data")
            continue
        if not train(args.python, args.weights, data, args.output, name,
                     epochs, size, batch, status):
            failed.append(f"{name}: training failed")
            continue
        model = args.output / name / "weights" / "best.pt"
        if test_split and (data / test_split).is_dir():
            command = [str(Path(args.python).with_name("yolo")), "classify", "val",
                       f"model={model}", f"data={data}", f"split={test_split}",
                       "device=0", f"imgsz={size}", f"batch={batch}",
                       "workers=4", "plots=False", f"project={args.output}",
                       f"name={name}-heldout", "exist_ok=True"]
            if not run(command, f"avaliação separada {name}", status):
                failed.append(f"{name}: heldout evaluation failed")
    summary = {"state": "finished", "failures": failed,
               "warning": "Item validation reuses source artwork; digit labels are OCR proposals, not human truth."}
    status.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

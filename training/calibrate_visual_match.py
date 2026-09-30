from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Example:
    similarity: float
    margin: float
    label: int


@dataclass(frozen=True)
class Model:
    bias: float
    similarity_weight: float
    margin_weight: float

    def predict(self, example: Example) -> float:
        z = (
            self.bias
            + self.similarity_weight * example.similarity
            + self.margin_weight * example.margin
        )
        return sigmoid(z)


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def load_examples(path: Path) -> list[Example]:
    rows: list[Example] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"similarity", "margin", "label"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CSV must contain columns: {', '.join(sorted(required))}"
            )

        for line_no, row in enumerate(reader, start=2):
            similarity = float(row["similarity"])
            margin = float(row["margin"])
            label = int(row["label"])
            if not math.isfinite(similarity) or not math.isfinite(margin):
                raise ValueError(f"non-finite value at line {line_no}")
            if label not in (0, 1):
                raise ValueError(f"label must be 0 or 1 at line {line_no}")
            rows.append(Example(similarity, margin, label))

    if len(rows) < 4:
        raise ValueError("at least 4 labeled examples are required")
    if len({row.label for row in rows}) < 2:
        raise ValueError("dataset must contain both positive and negative labels")
    return rows


def train(
    examples: list[Example],
    *,
    epochs: int = 4000,
    learning_rate: float = 0.05,
    l2: float = 1e-3,
) -> Model:
    if epochs <= 0:
        raise ValueError("epochs must be > 0")
    if learning_rate <= 0 or not math.isfinite(learning_rate):
        raise ValueError("learning_rate must be finite and > 0")
    if l2 < 0 or not math.isfinite(l2):
        raise ValueError("l2 must be finite and >= 0")

    bias = 0.0
    w_similarity = 0.0
    w_margin = 0.0
    n = float(len(examples))

    for _ in range(epochs):
        gb = 0.0
        gs = 0.0
        gm = 0.0

        for row in examples:
            p = sigmoid(bias + w_similarity * row.similarity + w_margin * row.margin)
            error = p - row.label
            gb += error
            gs += error * row.similarity
            gm += error * row.margin

        gb /= n
        gs = gs / n + l2 * w_similarity
        gm = gm / n + l2 * w_margin

        bias -= learning_rate * gb
        w_similarity -= learning_rate * gs
        w_margin -= learning_rate * gm

    return Model(bias, w_similarity, w_margin)


def log_loss(model: Model, examples: Iterable[Example]) -> float:
    rows = list(examples)
    total = 0.0
    for row in rows:
        p = min(max(model.predict(row), 1e-9), 1.0 - 1e-9)
        total += -(row.label * math.log(p) + (1 - row.label) * math.log(1 - p))
    return total / len(rows)


def brier(model: Model, examples: Iterable[Example]) -> float:
    rows = list(examples)
    return sum((model.predict(row) - row.label) ** 2 for row in rows) / len(rows)


def accuracy_at(model: Model, examples: Iterable[Example], threshold: float) -> float:
    rows = list(examples)
    correct = sum(
        int((model.predict(row) >= threshold) == bool(row.label))
        for row in rows
    )
    return correct / len(rows)


def split_deterministic(
    examples: list[Example],
    validation_fraction: float,
) -> tuple[list[Example], list[Example]]:
    if not 0.0 <= validation_fraction < 0.5:
        raise ValueError("validation_fraction must be in [0, 0.5)")
    if validation_fraction == 0.0:
        return examples, []

    every = max(2, round(1.0 / validation_fraction))
    train_rows: list[Example] = []
    validation_rows: list[Example] = []

    for index, row in enumerate(examples):
        (validation_rows if index % every == 0 else train_rows).append(row)

    if not train_rows or not validation_rows:
        return examples, []
    if len({r.label for r in train_rows}) < 2:
        return examples, []

    return train_rows, validation_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit shop visual-match confidence calibration."
    )
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=4000)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2", type=float, default=1e-3)
    parser.add_argument("--min-confidence", type=float, default=0.80)
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    args = parser.parse_args()

    if not 0.0 <= args.min_confidence <= 1.0:
        raise SystemExit("--min-confidence must be in [0,1]")

    examples = load_examples(args.csv)
    train_rows, validation_rows = split_deterministic(
        examples, args.validation_fraction
    )
    model = train(
        train_rows,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
    )

    evaluation_rows = validation_rows or train_rows
    payload = {
        "schema_version": 1,
        "model": "logistic_visual_match_calibration",
        "features": ["similarity", "margin"],
        "bias": model.bias,
        "similarity_weight": model.similarity_weight,
        "margin_weight": model.margin_weight,
        "min_confidence": args.min_confidence,
        "dataset": {
            "rows_total": len(examples),
            "rows_train": len(train_rows),
            "rows_validation": len(validation_rows),
        },
        "metrics": {
            "evaluation_split": "validation" if validation_rows else "train",
            "log_loss": log_loss(model, evaluation_rows),
            "brier": brier(model, evaluation_rows),
            "accuracy_at_0_5": accuracy_at(model, evaluation_rows, 0.5),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

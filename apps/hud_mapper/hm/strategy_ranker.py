"""Small JSON-only MLP inference: no pickle, Torch, downloads or GPU at runtime."""

import math

from .strategic_coach import FEATURES, SCOPE, number


class StrategyRanker:
    def __init__(self, document, catalog_sha256):
        if (
            document.get("schema_version") != 1
            or document.get("features") != list(FEATURES)
            or document.get("scope") != SCOPE
            or document.get("catalog_sha256") != catalog_sha256
            or document.get("objective_version") != 2
            or document.get("objective") != "synthetic_attribute_teacher_distillation"
            or document.get("evaluation_passed") is not True
        ):
            raise ValueError("strategy model is incompatible or unevaluated")
        self.w1, self.b1, self.w2, self.b2 = (
            document[k] for k in ("w1", "b1", "w2", "b2")
        )
        hidden = len(self.b1)
        if (
            not 1 <= hidden <= 64
            or len(self.w1) != hidden
            or len(self.w2) != hidden
            or any(len(row) != len(FEATURES) for row in self.w1)
        ):
            raise ValueError("invalid strategy model shape")
        flat = [v for row in self.w1 for v in row] + self.b1 + self.w2 + [self.b2]
        if not all(number(v, -100, 100) for v in flat):
            raise ValueError("nonfinite or excessive model parameter")
        self.identity = document["training_run_id"]

    def predict(self, features):
        if not 1 <= len(features) <= 2048:
            raise ValueError("strategy batch exceeds bounded budget")
        result = []
        for x in features:
            if len(x) != len(FEATURES) or not all(number(v, -20, 20) for v in x):
                raise ValueError("strategy features outside supported range")
            h = [
                math.tanh(sum(a * b for a, b in zip(row, x)) + bias)
                for row, bias in zip(self.w1, self.b1)
            ]
            result.append(sum(a * b for a, b in zip(self.w2, h)) + self.b2)
        return result

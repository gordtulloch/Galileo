#!/usr/bin/env python3
"""Standalone demo: classify a single all-sky frame without a Galileo host.

Usage:
    python examples/demo.py path/to/frame.jpg --model keras_model.h5 --labels labels.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mlclouddetect_plugin.classifier import CloudClassifier


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Path to an all-sky camera frame")
    parser.add_argument("--model", type=Path, default=Path("keras_model.h5"))
    parser.add_argument("--labels", type=Path, default=Path("labels.txt"))
    args = parser.parse_args()

    classifier = CloudClassifier(
        model_path=str(args.model),
        labels_path=str(args.labels) if args.labels.is_file() else None,
    )
    result = classifier.classify(args.image)
    print(f"label={result.label} confidence={result.confidence:.3f} raw_scores={result.raw_scores}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

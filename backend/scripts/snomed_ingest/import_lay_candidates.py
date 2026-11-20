"""Import and convert lay description candidates to canonical format."""

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any


def convert_candidates(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Convert raw candidate rows into standardized lay descriptions format."""
    phrases: list[dict[str, str]] = [
        {
            "anchor_id": str(row["anchor_concept_id"]),
            "text": str(row["phrase"]),
            "source": str(row["source"]),
            "status": "confirmed" if row.get("agree_top3") else "generated",
        }
        for row in rows
    ]
    return {
        "version": 1,
        "phrases": phrases,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Convert candidate lay descriptions to the canonical lay descriptions format."
    )
    this_dir = Path(__file__).resolve().parent
    default_candidates = (
        this_dir.parent / "embedding_eval" / "results" / "lay_description_candidates.json"
    )
    default_out = this_dir / "data" / "lay_descriptions.json"

    parser.add_argument(
        "--candidates",
        type=Path,
        default=default_candidates,
        help="Path to candidate JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=default_out,
        help="Path to output JSON file (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    candidates_path = Path(args.candidates)
    out_path = Path(args.out)

    with open(candidates_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    converted = convert_candidates(rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(converted, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()

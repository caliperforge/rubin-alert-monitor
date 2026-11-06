import json
from collections import Counter
from pathlib import Path

TABLE = json.loads((Path(__file__).parent / "labels_map.json").read_text())


def normalise(broker: str, raw: str) -> str:
    return TABLE[broker].get(raw, "unknown")


def unmapped(records: list[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = {}
    for record in records:
        for label in record["labels"]:
            if label["raw"] not in TABLE[label["broker"]]:
                counts.setdefault(label["broker"], Counter())[label["raw"]] += 1
    return {broker: dict(c) for broker, c in counts.items()}

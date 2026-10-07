"""Copy trusted release inputs into a new directory; never modify originals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.entrypoint import ARTIFACTS, digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("graph", "towers", "model", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    sources = [args.graph.resolve(strict=True), args.towers.resolve(strict=True), args.model.resolve(strict=True)]
    if any(not source.is_file() or not source.stat().st_size for source in sources):
        parser.error("All inputs must be nonempty regular files")
    args.output.mkdir(parents=True, exist_ok=False)
    for source, name in zip(sources, ARTIFACTS):
        shutil.copyfile(source, args.output / name)
    manifest = {"schema": 1, "sha256": {name: digest(args.output / name) for name in ARTIFACTS},
                "provenance": "Unknown tower/model training provenance; hashes do not establish quality"}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared three immutable input copies and checksum manifest in {args.output}")


if __name__ == "__main__":
    main()

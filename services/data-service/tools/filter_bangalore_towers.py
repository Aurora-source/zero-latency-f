from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "data" / "raw" / "cell_towers_IN.csv"
OUTPUT_CSV = ROOT / "data" / "towers" / "towers_bangalore.csv"

BANGALORE_BBOX = {
    "min_lat": 12.834,
    "max_lat": 13.139,
    "min_lon": 77.460,
    "max_lon": 77.750,
}

# Maps all known variants -> canonical name
COLUMN_ALIASES = {
    # latitude
    "lat":       "lat",
    "latitude":  "lat",
    # longitude
    "lon":       "lon",
    "long":      "lon",       # <-- your CSV uses "long"
    "longitude": "lon",
    # cell id
    "cell":      "cell",
    "cellid":    "cell",
    "cid":       "cell",      # <-- your CSV uses "cid"
    # network / mnc
    "net":       "net",
    "mnc":       "net",
    # area / lac
    "area":      "area",
    "lac":       "area",      # <-- your CSV uses "lac"
    # everything else passes through unchanged
}

KEEP_COLUMNS = {"radio", "mcc", "net", "area", "cell", "lon", "lat", "range", "sample", "avgsignal"}


def main() -> None:
    if not RAW_CSV.exists():
        raise SystemExit(f"Raw tower dataset not found: {RAW_CSV}")

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    chunks: list[pd.DataFrame] = []

    for chunk in pd.read_csv(RAW_CSV, chunksize=250_000, low_memory=False):
        # 1. Lowercase + strip all column names
        chunk.columns = [str(c).strip().lower() for c in chunk.columns]

        # 2. Rename using alias map
        chunk = chunk.rename(columns=COLUMN_ALIASES)

        # 3. Validate lat/lon exist after renaming
        if "lat" not in chunk.columns or "lon" not in chunk.columns:
            print(f"Columns found: {list(chunk.columns)}")
            raise SystemExit(
                "Could not find lat/lon columns. "
                f"Columns in file: {list(chunk.columns)}"
            )

        # 4. Filter to Bangalore bounding box
        filtered = chunk[
            (chunk["lat"] >= BANGALORE_BBOX["min_lat"])
            & (chunk["lat"] <= BANGALORE_BBOX["max_lat"])
            & (chunk["lon"] >= BANGALORE_BBOX["min_lon"])
            & (chunk["lon"] <= BANGALORE_BBOX["max_lon"])
        ].copy()

        # 5. Keep only columns that exist in this chunk
        keep = [c for c in KEEP_COLUMNS if c in filtered.columns]
        chunks.append(filtered[keep])

    if not chunks:
        raise SystemExit("No Bangalore towers matched — check bounding box or MCC filter")

    bangalore = pd.concat(chunks, ignore_index=True).drop_duplicates()

    # Filter to India MCCs just in case the file is worldwide
    if "mcc" in bangalore.columns:
        bangalore = bangalore[bangalore["mcc"].isin([404, 405])]

    bangalore.to_csv(OUTPUT_CSV, index=False)
    print(f"[local-towers] wrote {len(bangalore)} Bangalore towers → {OUTPUT_CSV}")
    print(f"Columns saved: {list(bangalore.columns)}")
    print(bangalore.head(3).to_string())


if __name__ == "__main__":
    main()
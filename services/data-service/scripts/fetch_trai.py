from __future__ import annotations

import os
from pathlib import Path

import httpx

OPENCELLID_TOKEN = os.environ.get(
    "OPENCELLID_TOKEN",
    "",
).strip()

CITY_BBOXES = {
    "bangalore": {
        "min_lat": 12.8,
        "max_lat": 13.1,
        "min_lon": 77.4,
        "max_lon": 77.8,
    },
    "chennai": {
        "min_lat": 12.9,
        "max_lat": 13.2,
        "min_lon": 80.1,
        "max_lon": 80.3,
    },
}

SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_DIR = SCRIPT_DIR.parent
TOWER_DIR = SERVICE_DIR / "data" / "towers"


def main() -> None:
    if not OPENCELLID_TOKEN:
        raise SystemExit(
            "OPENCELLID_TOKEN is required for this optional fetch; no request was made."
        )

    TOWER_DIR.mkdir(parents=True, exist_ok=True)

    for city, bbox in CITY_BBOXES.items():
        url = "https://opencellid.org/cell/getInArea"
        params = {
            "token": OPENCELLID_TOKEN,
            "BBOX": (
                f"{bbox['min_lat']},{bbox['min_lon']},"
                f"{bbox['max_lat']},{bbox['max_lon']}"
            ),
            "format": "csv",
        }
        output_path = TOWER_DIR / f"{city}_towers.csv"

        print(f"[fetch] calling OpenCellID bbox API for {city}...")
        try:
            response = httpx.get(
                url,
                params=params,
                timeout=120,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/csv,application/json",
                },
            )
            print(f"[fetch] HTTP {response.status_code}")
            print(f"[fetch] Content length: {len(response.content)} bytes")

            if response.status_code == 200:
                first_line = response.text.strip().split("\n", 1)[0]
                if any(token in first_line.lower() for token in ("radio", "lat", "lon", "cell")):
                    output_path.write_text(response.text, encoding="utf-8")
                    tower_count = max(len(response.text.strip().splitlines()) - 1, 0)
                    print(f"[fetch] OK {city}: {tower_count} towers saved")
                else:
                    print("[fetch] ERROR Response was not a recognized CSV payload")
            else:
                print(f"[fetch] ERROR HTTP {response.status_code}")
        except Exception as exc:
            print(f"[fetch] ERROR {city}: {type(exc).__name__}; request failed")


if __name__ == "__main__":
    main()

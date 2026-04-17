from __future__ import annotations

from pathlib import Path

import osmnx as ox

CITY_QUERIES = {
    "chennai": "Chennai, Tamil Nadu, India",
    "mumbai": "Mumbai, Maharashtra, India",
    "delhi": "National Capital Territory of Delhi, India",
}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
GRAPH_DIR = DATA_DIR / "graphs"
CACHE_DIR = DATA_DIR / "osmnx_cache"

GRAPH_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ox.settings.use_cache = True
ox.settings.cache_folder = str(CACHE_DIR)
ox.settings.log_console = False


def normalize_city(city: str) -> str:
    city_slug = city.strip().lower()
    if city_slug not in CITY_QUERIES:
        supported = ", ".join(sorted(CITY_QUERIES))
        raise ValueError(f"Unsupported city '{city}'. Supported cities: {supported}.")
    return city_slug


def graph_path(city: str) -> Path:
    return GRAPH_DIR / f"{normalize_city(city)}.graphml"


def download_graph(city: str):
    city_slug = normalize_city(city)
    graph = ox.graph_from_place(
        CITY_QUERIES[city_slug],
        network_type="drive",
        simplify=True,
        retain_all=False,
        truncate_by_edge=True,
    )
    ox.save_graphml(graph, graph_path(city_slug))
    return graph


def load_graph(city: str):
    path = graph_path(city)
    if path.exists():
        return ox.load_graphml(path)
    return download_graph(city)


def main() -> None:
    for city in CITY_QUERIES:
        print(f"[predownload] ensuring cached graph for {city}")
        load_graph(city)
    print("[predownload] graph cache is ready")


if __name__ == "__main__":
    main()

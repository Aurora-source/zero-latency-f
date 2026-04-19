import osmium

INPUT  = r"C:\Users\Rikon\zero-latency-f\connectivity-aware-routing\services\data-service\southern-zone-260416.osm.pbf"
OUTPUT = r"C:\Users\Rikon\zero-latency-f\connectivity-aware-routing\services\data-service\bangalore.osm.pbf"

# Bangalore bounding box
# Bangalore core urban area only (reduced from original)
MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = 77.48, 12.85, 77.72, 13.05

DRIVE_HIGHWAY_TYPES = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "residential", "living_street",
    "unclassified", "road",
}

# ── Pass 1: find way node IDs within bbox ─────────────────────────────────
class WayScanner(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.needed_nodes = set()
        self.ways = []  # (node_ids, tags)

    def way(self, w):
        hw = w.tags.get("highway")
        if hw not in DRIVE_HIGHWAY_TYPES:
            return
        node_ids = [n.ref for n in w.nodes]
        self.ways.append((node_ids, {t.k: t.v for t in w.tags}))
        self.needed_nodes.update(node_ids)

print("Pass 1 — scanning ways...")
ws = WayScanner()
ws.apply_file(INPUT, locations=False)
print(f"  {len(ws.ways)} drive ways found across full region")

# ── Pass 2: resolve node locations, keep only those inside bbox ───────────
class NodeScanner(osmium.SimpleHandler):
    def __init__(self, needed):
        super().__init__()
        self.needed = needed
        self.nodes = {}  # id -> (lat, lon)

    def node(self, n):
        if n.id not in self.needed:
            return
        lat, lon = n.location.lat, n.location.lon
        if MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON:
            self.nodes[n.id] = (lat, lon)

print("Pass 2 — resolving node locations inside Bangalore bbox...")
ns = NodeScanner(ws.needed_nodes)
ns.apply_file(INPUT, locations=True)
print(f"  {len(ns.nodes)} nodes inside bbox")

# ── Filter ways to only those with ALL nodes resolvable inside bbox ────────
import math, networkx as nx, osmnx as ox
from pathlib import Path

bbox_ways = [
    (nids, tags) for nids, tags in ws.ways
    if all(n in ns.nodes for n in nids)
]
print(f"  {len(bbox_ways)} ways fully inside bbox")

# ── Build graph ────────────────────────────────────────────────────────────
print("Building graph...")
G = nx.MultiDiGraph()
G.graph["crs"] = "epsg:4326"

for node_id, (lat, lon) in ns.nodes.items():
    G.add_node(node_id, y=lat, x=lon, lat=lat, lon=lon, street_count=0)

def haversine(n1, n2):
    lat1, lon1 = ns.nodes[n1]
    lat2, lon2 = ns.nodes[n2]
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def normalize_tags(tags, u, v):
    result = {}
    for k, val in tags.items():
        if k == "oneway":
            result[k] = val in ("yes", "true", "1", "-1")

        elif k in ("lanes", "layer", "bridge", "tunnel"):
            # Keep only clean integers; drop garbage like "2;3"
            try:
                result[k] = int(val.split(";")[0].strip())
            except (ValueError, AttributeError):
                pass  # drop the attribute entirely if unparseable

        elif k == "maxspeed":
            # Normalize to numeric string OSMnx can handle, or drop it
            val_clean = val.strip().lower()
            if val_clean in ("none", "unlimited", "signals", "walk", "living_street", ""):
                pass  # drop unparseable maxspeed
            else:
                # Strip units like "50 mph", "50 km/h"
                numeric = val_clean.split()[0]
                try:
                    result[k] = str(int(float(numeric)))
                except ValueError:
                    pass  # drop if still not numeric

        elif k in ("access", "junction", "surface", "service",
                   "highway", "name", "ref", "width"):
            # Keep as plain string, just strip whitespace
            result[k] = str(val).strip()

        else:
            # Keep everything else as string
            result[k] = str(val).strip()

    result["length"] = haversine(u, v)
    return result

for node_ids, tags in bbox_ways:
    oneway = tags.get("oneway", "no") in ("yes", "true", "1", "-1")
    reverse = tags.get("oneway") == "-1"
    for i in range(len(node_ids) - 1):
        u = node_ids[i]   if not reverse else node_ids[i+1]
        v = node_ids[i+1] if not reverse else node_ids[i]
        if u not in ns.nodes or v not in ns.nodes:
            continue
        # Normalize oneway to bool so OSMnx can load the GraphML correctly
        edata = normalize_tags(tags, u, v)
        G.add_edge(u, v, **edata)
        if not oneway:
            G.add_edge(v, u, **edata)

isolated = list(nx.isolates(G))
G.remove_nodes_from(isolated)
largest = max(nx.weakly_connected_components(G), key=len)
G = G.subgraph(largest).copy()

print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

OUT = Path(r"C:\Users\Rikon\zero-latency-f\connectivity-aware-routing\services\data-service\data\graphs\bangalore.graphml")
OUT.parent.mkdir(parents=True, exist_ok=True)
ox.save_graphml(G, OUT)
print(f"Saved to {OUT}")
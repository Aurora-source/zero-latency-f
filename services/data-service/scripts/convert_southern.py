from pathlib import Path
import osmium
import networkx as nx
import osmnx as ox

print("[convert] Starting Bangalore graph extraction...")

BASE_DIR = Path(__file__).resolve().parent.parent
PBF_FILE = str(BASE_DIR / "southern-zone-260416.osm.pbf")
GRAPH_DIR = BASE_DIR / "data" / "graphs"
GRAPH_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = GRAPH_DIR / "bangalore.graphml"

print(f"[convert] Looking for PBF at: {PBF_FILE}")
if not Path(PBF_FILE).exists():
    raise FileNotFoundError(f"[convert] PBF file not found at {PBF_FILE}")

# Drive-network highway types (mirrors OSMnx's "drive" filter)
DRIVE_HIGHWAY_TYPES = {
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "residential", "living_street",
    "unclassified", "road",
}

# ── Pass 1: collect all drive-network way node IDs and way metadata ──────────
class WayHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = []          # list of (node_id_list, tags_dict)
        self.needed_nodes = set()

    def way(self, w):
        hw = w.tags.get("highway")
        if hw not in DRIVE_HIGHWAY_TYPES:
            return
        node_ids = [n.ref for n in w.nodes]
        tags = {t.k: t.v for t in w.tags}
        self.ways.append((node_ids, tags))
        self.needed_nodes.update(node_ids)

print("[convert] Pass 1 — scanning ways...")
wh = WayHandler()
wh.apply_file(PBF_FILE, locations=False)
print(f"[convert]   Found {len(wh.ways)} drive ways, {len(wh.needed_nodes)} unique nodes needed")

# ── Pass 2: collect lat/lon for only the nodes we need ───────────────────────
class NodeHandler(osmium.SimpleHandler):
    def __init__(self, needed):
        super().__init__()
        self.needed = needed
        self.nodes = {}   # node_id -> (lat, lon)

    def node(self, n):
        if n.id in self.needed:
            self.nodes[n.id] = (n.location.lat, n.location.lon)

print("[convert] Pass 2 — collecting node locations...")
nh = NodeHandler(wh.needed_nodes)
nh.apply_file(PBF_FILE, locations=True)
print(f"[convert]   Resolved {len(nh.nodes)} node locations")

# ── Build NetworkX MultiDiGraph ───────────────────────────────────────────────
print("[convert] Building graph...")
G = nx.MultiDiGraph()
G.graph["crs"] = "epsg:4326"

# Add nodes
for node_id, (lat, lon) in nh.nodes.items():
    G.add_node(node_id, y=lat, x=lon, lat=lat, lon=lon, street_count=0)

# Add edges from ways
for node_ids, tags in wh.ways:
    oneway = tags.get("oneway", "no") in ("yes", "true", "1", "-1")
    reverse = tags.get("oneway") == "-1"

    for i in range(len(node_ids) - 1):
        u = node_ids[i] if not reverse else node_ids[i + 1]
        v = node_ids[i + 1] if not reverse else node_ids[i]

        # Skip edges whose nodes weren't resolved
        if u not in nh.nodes or v not in nh.nodes:
            continue

        edge_data = {k: v_val for k, v_val in tags.items()}

        # Calculate length in metres using great-circle distance
        lat1, lon1 = nh.nodes[u]
        lat2, lon2 = nh.nodes[v]
        import math
        R = 6_371_000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2)**2
        edge_data["length"] = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        G.add_edge(u, v, **edge_data)
        if not oneway:
            G.add_edge(v, u, **edge_data)

# Drop isolated nodes
isolated = list(nx.isolates(G))
G.remove_nodes_from(isolated)

# Keep only the largest weakly connected component
largest_wcc = max(nx.weakly_connected_components(G), key=len)
G = G.subgraph(largest_wcc).copy()

print(f"[convert] Graph has {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")

print("[convert] Saving Bangalore graph...")
ox.save_graphml(G, OUTPUT_FILE)
print(f"[convert] Done. Saved to {OUTPUT_FILE}")
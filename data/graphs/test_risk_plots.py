import osmnx as ox
import networkx as nx
import matplotlib.pyplot as plt

# 1. Load your existing Chennai graph
G = ox.load_graphml("./data/graphs/chennai.graphml")

# 2. Define a "Risk Zone" (e.g., a known flood-prone area in Chennai)
# Let's say roads near a specific point are 'risky'
risk_center = (13.0475, 80.2089) # Coordinates for a part of Chennai
dist_threshold = 500 # meters

# 3. Apply Risk Penalties to the Graph
for u, v, k, data in G.edges(data=True, keys=True):
    # Calculate distance from road to risk center
    node_coords = (G.nodes[u]['y'], G.nodes[u]['x'])
    dist = ox.distance.great_circle_vec(risk_center[0], risk_center[1], node_coords[0], node_coords[1])
    
    # If close to flood zone, triple the weight
    data['risk_weight'] = data['length'] * (3.0 if dist < dist_threshold else 1.0)
    data['normal_weight'] = data['length']

# 4. Calculate two different paths
orig = ox.nearest_nodes(G, 80.20, 13.04)
dest = ox.nearest_nodes(G, 80.22, 13.05)

path_normal = nx.shortest_path(G, orig, dest, weight='normal_weight')
path_risk = nx.shortest_path(G, orig, dest, weight='risk_weight')

# 5. Visualize immediately
fig, ax = ox.plot_graph_routes(G, [path_normal, path_risk], route_colors=['blue', 'red'], route_linewidth=5, node_size=0)
plt.show()
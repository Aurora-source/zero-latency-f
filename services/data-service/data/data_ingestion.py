import osmnx as ox
import pandas as pd
import json

def ingest_city_data(city_name, city_query):
    print(f"--- Starting Ingestion for {city_name} ---")
    
    # 1. Download the drive network
    # This matches the 'load_graph' logic in your main.py
    graph = ox.graph_from_place(city_query, network_type="drive")
    
    # 2. Convert edges to a GeoDataFrame to easily manipulate them
    nodes, edges = ox.graph_to_gdfs(graph)
    
    # 3. Apply your Fusion Logic (Placeholder for your JSON math)
    # For Phase 1, we initialize every road with a baseline score
    edges['connectivity_score'] = 0.5 
    
    # 4. Save to the directory the Routing Engine expects
    save_path = f"./data/graphs/{city_name.lower()}.graphml"
    ox.save_graphml(ox.graph_from_gdfs(nodes, edges), save_path)
    
    print(f"Successfully saved enriched graph to {save_path}")

if __name__ == "__main__":
    # Example for Chennai as per your roadmap
    ingest_city_data("chennai", "Chennai, Tamil Nadu, India")
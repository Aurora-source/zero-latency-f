import osmium

INPUT  = r"C:\Users\Rikon\zero-latency-f\connectivity-aware-routing\services\data-service\southern-zone-260416.osm.pbf"
OUTPUT = r"C:\Users\Rikon\zero-latency-f\connectivity-aware-routing\services\data-service\bangalore.osm.pbf"

# Bangalore bounding box: left, bottom, right, top
BBOX = osmium.osm.Box(77.4, 12.8, 77.8, 13.1)

print("Clipping to Bangalore bbox...")
osmium.extract.extract(
    INPUT,
    OUTPUT,
    osmium.extract.BBoxStrategy(BBOX)
)
print(f"Done. Saved to {OUTPUT}")
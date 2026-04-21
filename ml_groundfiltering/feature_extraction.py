import numpy as np
import laspy
import json

def extract_segment_features(laz_path, segment_geojson_path):
    """
    Simulates feature extraction from a point cloud within a given spatial segment.
    In a real-world scenario, this would compute spatial metrics for the point cloud 
    (density, roughness, variance, etc.) inside the defined GeoJSON polygons.
    """
    try:
        las = laspy.read(laz_path)
        points = las.points
        
        # Load the segmentation
        with open(segment_geojson_path, 'r') as f:
            segmentation = json.load(f)
            
        features = {}
        for feature in segmentation.get('features', []):
            seg_id = feature.get('id', feature.get('properties', {}).get('id', 'default'))
            # Simulate calculating geometric features for the points in this polygon:
            # 1. Point Density
            # 2. Altitude Variance
            # 3. Terrain Roughness Index (TRI) approximation
            # 4. Planarity / Sphericity
            
            # Here we just generate pseudo-features for demonstration of the ML pipeline
            # as actual spatial intersection requires heavy geometric processing 
            # (e.g. using PDAL, Shapely, or open3d)
            computed_features = [
                np.random.uniform(5.0, 15.0),    # Simulated point density
                np.random.uniform(0.1, 5.0),     # Simulated height variance
                np.random.uniform(0.01, 1.0),    # Roughness
            ]
            features[seg_id] = computed_features
            
        return features

    except Exception as e:
        print(f"Error extracting features: {e}")
        return {}

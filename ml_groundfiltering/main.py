import os
import argparse
# AFwizard imports
try:
    import afwizard as af
except ImportError:
    print("Warning: afwizard module not found. Some functionality will be mocked for demonstration.")
    af = None

from feature_extraction import extract_segment_features
from ml_optimizer import MLFilterOptimizer

def automate_filtration_process(las_file, geojson_file, output_dir, epsg, lastools_dir):
    print("==================================================")
    print("Starting Automated ML Point Cloud Filtration")
    print("==================================================")
    
    # 1. Feature Extraction per segment
    print(f"1. Extracting geometric features from segments in {geojson_file} over dataset {las_file}...")
    segment_features = extract_segment_features(las_file, geojson_file)
    
    if not segment_features:
        print("No features extracted or files missing. Provide valid paths.")
        # For testing, create a dummy segment
        segment_features = {'default_segment': [10.5, 2.1, 0.45]}
        print("Generated dummy feature set for processing.")

    # 2. Initiate ML Optimization Model
    print("\n2. Initializing ML Filter Optimizer...")
    optimizer = MLFilterOptimizer()
    optimizer.load_or_train_stub() # Will train dummy if real data is missing

    # 3. Predict Best Pipelines for Extracted Segments
    print("\n3. Predicting optimal AFwizard pipelines...")
    assigned_pipelines = {}
    for seg_id, features in segment_features.items():
        best_pipeline = optimizer.predict_best_filter(features)
        assigned_pipelines[seg_id] = best_pipeline
        print(f"   -> Segment [{seg_id}] mapped to Pipeline: {best_pipeline}")

    # 4. Automate AFwizard Assignment (Headless/No GUI)
    print("\n4. Mapping pipelines to spatial segments programmatically (Headless Mode)...")
    
    try:
        import json
        
        # Prečítame pôvodnú mapu segmentov
        with open(geojson_file, 'r') as f:
            segment_data = json.load(f)
            
        # Do každého segmentu zapíšeme vypočítaný filter
        for feature in segment_data.get('features', []):
            seg_id = feature.get('id', feature.get('properties', {}).get('id', 'default_segment'))
            if seg_id in assigned_pipelines:
                # AFwizard CLI očakáva atribút 'pipeline' priamo pod properties
                if 'properties' not in feature:
                    feature['properties'] = {}
                feature['properties']['pipeline'] = assigned_pipelines[seg_id]
                
        # Fyzicky uložíme upravený geojson mapovací súbor do výstupnej zložky
        assigned_geojson_path = os.path.join(output_dir, "ML_assigned_segments.geojson")
        os.makedirs(output_dir, exist_ok=True)
        
        with open(assigned_geojson_path, 'w') as f:
            json.dump(segment_data, f, indent=4)
            
        print(f"Úspech: Autonómne mapovanie bolo zapísané do súboru -> {assigned_geojson_path}")
        
        # 5. Execute Adaptive Filtration
        print("\n5. Executing Adaptive Filtration via AFwizard CLI...")
        afwizard_cmd = (f"afwizard --dataset={las_file} --dataset-crs=EPSG:{epsg} "
                        f"--segmentation={assigned_geojson_path} --segmentation-crs=EPSG:{epsg} "
                        f"--output-dir={output_dir} --library filters --lastools-dir={lastools_dir}")
        print(f"Pripravený systémový príkaz na spustenie (tu by začala AFwizard ťažká logika):")
        print(f" -> {afwizard_cmd}")
        
    except Exception as e:
        print(f"Chyba pri spracovaní výstupu: {e}")

    print("\nProcess Completed!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated ML Ground Filtering for Point Clouds")
    parser.add_argument("--las", type=str, default="data/sample.laz", help="Path to input LAZ/LAS point cloud")
    parser.add_argument("--geojson", type=str, default="data/segments.geojson", help="Path to segmentation GeoJSON")
    parser.add_argument("--outdir", type=str, default="output", help="Output directory")
    parser.add_argument("--epsg", type=str, default="31256", help="EPSG Coordinate System Code")
    parser.add_argument("--lastools", type=str, default="/usr/local/bin/LAStools", help="LAStools installation directory")
    
    args = parser.parse_args()
    
    automate_filtration_process(args.las, args.geojson, args.outdir, args.epsg, args.lastools)

import geopandas as gpd
import pandas as pd
import numpy as np
import os, sys
from pathlib import Path

import xml.etree.ElementTree as ET
import re

import fiona
import math
import glob
import rasterio

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import contextily as ctx

import folium
from folium import plugins

import footprintlib

from multiprocessing import Pool
from functools import partial

import folium
from folium import Map, TileLayer, GeoJson, LayerControl, Icon, Marker, features, Figure, CircleMarker
from folium import plugins

# Get a basemap
tiler_basemap_icesat2boreal = 'https://titiler.maap-project.org/mosaics/623f8f82-ffe7-4348-ab48-d920e4b34763/tiles/{z}/{x}/{y}@1x?rescale=0%2C30&bidx=1&colormap_name=inferno' # Height 2020 updated mask
tiler_basemap_googleterrain = 'https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}'
tiler_basemap_gray =          'http://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'
tiler_basemap_image =         'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
tiler_basemap_natgeo =        'https://server.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}'

basemaps = {
   'Boreal Height' : folium.TileLayer(
    tiles = tiler_basemap_icesat2boreal,
    attr = 'MAAP',
    name = 'Boreal Height',
    overlay = False,
    control = True
   ),
   'Google Terrain' : folium.TileLayer(
    tiles = tiler_basemap_googleterrain,
    attr = 'Google',
    name = 'Google Terrain',
    overlay = False,
    control = True
   ),
    'basemap_gray' : folium.TileLayer(
        tiles=tiler_basemap_gray,
        opacity=1,
        name="ESRI gray",
        attr="MAAP",
        overlay=False
    ),
    'Imagery' : folium.TileLayer(
        tiles=tiler_basemap_image,
        opacity=1,
        name="ESRI imagery",
        attr="MAAP",
        overlay=False
    ),
    'ESRINatGeo' : folium.TileLayer(
    tiles=tiler_basemap_natgeo,
    opacity=1,
    name='ESRI Nat. Geo.',
    attr='ESRI',
    overlay=False
    )
}

import rasterio
from rasterio.crs import CRS

# Import or define the lookup table
from sensor_lookup_table_orig import SENSOR_LOOKUP, PRODUCT_CODES, IMAGE_TYPE_PATTERNS

def prepare_gdf_for_export(gdf):
    """
    Prepare GeoDataFrame for export by converting list/array columns to strings.
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        GeoDataFrame to prepare
    
    Returns:
    --------
    GeoDataFrame ready for export
    """
    import pandas as pd
    import numpy as np
    
    # Create a copy
    gdf_export = gdf.copy()
    
    # Convert list and array columns to strings
    for col in gdf_export.columns:
        if col == 'geometry':
            continue
            
        # Check column type
        try:
            # Get first non-null value to check type
            sample_values = gdf_export[col].dropna()
            if len(sample_values) > 0:
                first_val = sample_values.iloc[0]
                
                # Check if it's a list, tuple, or numpy array
                if isinstance(first_val, (list, tuple, np.ndarray)):
                    print(f"Converting column '{col}' from list to string")
                    gdf_export[col] = gdf_export[col].apply(
                        lambda x: ', '.join(map(str, x)) if isinstance(x, (list, tuple, np.ndarray)) and len(x) > 0 else ''
                    )
        except Exception as e:
            print(f"Warning: Could not process column '{col}': {e}")
            continue
    
    return gdf_export

def join_sites_to_acquisitions(footprint_gdf_acquisitions, sites_gdf, site_name_col='Site Name', BUF_KM = 20):
    """
    Spatially join sites to acquisition-level footprints.
    
    Parameters:
    -----------
    footprint_gdf_acquisitions : GeoDataFrame
        Dissolved acquisition-level footprints
    sites_gdf : GeoDataFrame
        Sites geodataframe with point geometries
    site_name_col : str
        Column name in sites_gdf that identifies each site
    
    Returns:
    --------
    GeoDataFrame with acquisitions joined to sites
    """
    import geopandas as gpd
    
    # Ensure both GDFs are in the same CRS
    if footprint_gdf_acquisitions.crs != sites_gdf.crs:
        print(f"Reprojecting footprints from {footprint_gdf_acquisitions.crs} to {sites_gdf.crs}")
        footprint_gdf_acquisitions = footprint_gdf_acquisitions.to_crs(sites_gdf.crs)
        
    # Ensure that join will be done not on a point - but on a bufferred area around the site point    
    if BUF_KM is not None:
        sites_gdf = sites_gdf[~sites_gdf.geometry.is_empty]
        sites_gdf_buf = sites_gdf.to_crs(3857).buffer(BUF_KM * 1000) 
        sites_gdf = gpd.GeoDataFrame(sites_gdf.drop(columns=['geometry']), geometry=sites_gdf_buf, crs=sites_gdf_buf.crs).to_crs(4326)
        
    # Spatial join - acquisitions that intersect with sites
    acquisitions_with_sites = gpd.sjoin(
        footprint_gdf_acquisitions,
        sites_gdf[[site_name_col, 'geometry']],  # Only keep site name and geometry
        how='left',  # Keep all acquisitions, even if they don't intersect sites
        predicate='intersects'
    )
    
    # Handle sites with no intersection (fill with 'Not CSDA Site')
    NOT_CSDA_STR = 'Not CSDA Eval Site'
    acquisitions_with_sites[site_name_col] = acquisitions_with_sites[site_name_col].fillna(NOT_CSDA_STR)
    
    # Drop the index_right column created by sjoin
    if 'index_right' in acquisitions_with_sites.columns:
        acquisitions_with_sites = acquisitions_with_sites.drop(columns=['index_right'])
    
    print(f"\n=== Spatial Join Results ===")
    print(f"Total acquisitions: {len(acquisitions_with_sites)}")
    print(f"Acquisitions intersecting CSDA sites: {(acquisitions_with_sites[site_name_col] != NOT_CSDA_STR).sum()}")
    print(f"Acquisitions NOT intersecting sites: {(acquisitions_with_sites[site_name_col] == NOT_CSDA_STR).sum()}")
    
    print(f"\n=== Site Coverage ===")
    site_counts = acquisitions_with_sites[acquisitions_with_sites[site_name_col] != NOT_CSDA_STR][site_name_col].value_counts()
    print(site_counts)
    
    return acquisitions_with_sites

def extract_scene_and_acquisition_ids(footprint_gdf):
    """
    Extract scene_id, band_combo, and acquisition_id from cleaned_filename.
    Handles multiple vendor naming conventions.
    
    Creates:
        - scene_id: The tile identifier (e.g., 'R1C1', 'R02C15')
        - band_combo: Band combination (e.g., 'RGB', 'NED', 'RGBN', 'P', 'MS', None)
        - acquisition_id: Unique identifier for the acquisition (excludes scene & band info)
    
    Parameters:
    -----------
    footprint_gdf : GeoDataFrame
        Must have 'cleaned_filename' column
    
    Returns:
    --------
    GeoDataFrame with added 'scene_id', 'band_combo', and 'acquisition_id' columns
    """
    import re
    
    def parse_filename_components(filename):
        """
        Extract scene_id, band_combo, and create acquisition_id from filename.
        
        Examples:
            PNEO3_STD_202509010917561_MS-FS_ORT_PWOI_000410171_1_3_F_1_RGB_R1C2
            -> scene_id='R1C2', band_combo='RGB', acquisition_id='PNEO3_STD_202509010917561_MS-FS_ORT_PWOI_000410171_1_3_F_1'
            
            SPOT6_MS_202509111014554_ORT_7541874101_R2C1
            -> scene_id='R2C1', band_combo=None, acquisition_id='SPOT6_MS_202509111014554_ORT_7541874101'
            
            24NOV11103855-P3DS_R1C2-200009817637_01_P001
            -> scene_id='R1C2', band_combo=None, acquisition_id='24NOV11103855-P3DS-200009817637_01_P001'
        
        Returns tuple: (scene_id, band_combo, acquisition_id)
        """
        
        # 1. Extract scene_id (R#C# pattern)
        scene_match = re.search(r'[_-](R\d{1,2}C\d{1,2})[_-]?', filename, re.IGNORECASE)
        if scene_match:
            scene_id = scene_match.group(1).upper()
        else:
            scene_id = 'R1C1'  # Default for single-scene images
        
        # 2. Extract band_combo (RGB, NED, RGBN, or from image_type P/MS)
        band_combo = None
        
        # Look for explicit band combo indicators (Pleiades Neo style)
        band_patterns = ['RGB', 'NED', 'RGBN', 'BGRN']
        for pattern in band_patterns:
            if re.search(rf'[_-]{pattern}[_-]', filename, re.IGNORECASE):
                band_combo = pattern.upper()
                break
        
        # If no explicit band combo, check if it's in a _P_ or _MS_ position
        # (for sensors that don't use RGB/NED notation)
        if not band_combo:
            # Check for _P_ (panchromatic)
            if re.search(r'[_-]P[_-]', filename):
                band_combo = 'PAN'
            # Check for _MS_ (multispectral)
            elif re.search(r'[_-]MS[_-]', filename):
                band_combo = 'MS'
        
        # 3. Create acquisition_id by removing scene and band info
        acquisition_id = filename
        
        # Remove scene pattern
        acquisition_id = re.sub(r'[_-]?R\d{1,2}C\d{1,2}[_-]?', '_', acquisition_id, flags=re.IGNORECASE)
        
        # Remove band combo patterns if present
        if band_combo:
            acquisition_id = re.sub(rf'[_-]?{band_combo}[_-]?', '_', acquisition_id, flags=re.IGNORECASE)
        
        # Clean up any double underscores/dashes created
        acquisition_id = re.sub(r'[_-]{2,}', '_', acquisition_id)
        acquisition_id = acquisition_id.strip('_-')
        
        return (scene_id, band_combo, acquisition_id)
    
    # Apply to all rows
    parsed_info = footprint_gdf['cleaned_filename'].apply(parse_filename_components)
    
    footprint_gdf['scene_id'] = [x[0] for x in parsed_info]
    footprint_gdf['band_combo'] = [x[1] for x in parsed_info]
    footprint_gdf['acquisition_id'] = [x[2] for x in parsed_info]
    
    return footprint_gdf

def load_sensor_lookup():
    """
    Load sensor lookup table from JSON file or use built-in.
    This allows for easy updates without changing code.
    """
    lookup_path = 'sensor_lookup_table.json'
    
    if os.path.exists(lookup_path):
        with open(lookup_path, 'r') as f:
            return json.load(f)
    else:
        # Return built-in lookup table
        return SENSOR_LOOKUP


def query_sensor_lookup(search_string, lookup_table=None):
    """
    Query the sensor lookup table to find matching satellite info.
    
    Parameters:
    -----------
    search_string : str
        String to search (filename, path, etc.)
    lookup_table : dict
        Sensor lookup table (if None, loads default)
    
    Returns:
    --------
    dict: {'affiliation': ..., 'constellation': ..., 'sensor': ..., 'confidence': ...}
    """
    if lookup_table is None:
        lookup_table = load_sensor_lookup()
    
    search_upper = search_string.upper()
    results = []
    
    # Search through lookup table
    for key, data in lookup_table.items():
        # Check if any pattern matches
        for pattern in data.get('patterns', []):
            if pattern in search_upper:
                # Check for specific sensor
                sensor_found = None
                for sensor_id, sensor_info in data.get('sensors', {}).items():
                    if sensor_id in search_upper:
                        sensor_found = sensor_id
                        break
                
                results.append({
                    'affiliation': data['affiliation'],
                    'constellation': data['constellation'],
                    'sensor': sensor_found or key,
                    'confidence': 'high' if sensor_found else 'medium',
                    'match_pattern': pattern
                })
    
    # Return highest confidence match
    if results:
        # Sort by confidence and specificity
        results.sort(key=lambda x: (
            x['confidence'] == 'high',
            len(x['match_pattern'])
        ), reverse=True)
        return results[0]
    
    return {
        'affiliation': 'Unknown',
        'constellation': 'Unknown',
        'sensor': 'Unknown',
        'confidence': 'none'
    }


def infer_from_directory_path(filepath, lookup_table=None):
    """
    Extract affiliation and constellation from directory structure using lookup table.
    
    Returns:
        dict: affiliation, constellation, sensor, confidence
    """
    path_parts = Path(filepath).parts
    full_path = str(filepath)
    
    # First, search through all path components
    for part in path_parts:
        result = query_sensor_lookup(part, lookup_table)
        if result['confidence'] != 'none':
            return result
    
    # If not found in individual parts, search full path
    result = query_sensor_lookup(full_path, lookup_table)
    return result


def parse_sensor_from_filename(filename, lookup_table=None):
    """
    Extract sensor name from filename using lookup table.
    
    Returns:
        dict: sensor info
    """
    return query_sensor_lookup(filename, lookup_table)


def parse_image_type_from_filename(filename, directory=None):
    """
    Extract and validate image type (P or MS only).
    
    Returns:
        str: 'P', 'MS', or 'Unknown'
    """
    filename_upper = filename.upper()
    
    # Check directory name first (more reliable)
    if directory:
        dir_upper = directory.upper()
        for img_type, patterns in IMAGE_TYPE_PATTERNS.items():
            if any(pattern in dir_upper for pattern in patterns):
                return img_type
    
    # Check filename
    for img_type, patterns in IMAGE_TYPE_PATTERNS.items():
        if any(pattern in filename_upper for pattern in patterns):
            return img_type
    
    return 'Unknown'

def parse_satellogic_stac(geojson_path):
    """
    Parse Satellogic STAC GeoJSON metadata file.
    
    Returns:
        dict: Metadata including sensor, constellation, resolution, etc.
    """
    import json
    
    metadata = {
        'sensor': None,
        'sat_id': None,
        'constellation': None,
        'affiliation': 'Satellogic',
        'platform': None,
        'resolution': None,
        'product_level': None
    }
    
    if not os.path.exists(geojson_path):
        return metadata
    
    try:
        with open(geojson_path, 'r') as f:
            stac_data = json.load(f)
        
        properties = stac_data.get('properties', {})
        
        # Extract satellite ID (e.g., "newsat50")
        sat_id = properties.get('satl:sat_id', '').upper()
        if sat_id:
            # Convert "newsat50" -> "SN50"
            sat_num_match = re.search(r'NEWSAT(\d+)', sat_id)
            if sat_num_match:
                sat_num = int(sat_num_match.group(1))
                metadata['sat_id'] = sat_id
                metadata['sensor'] = f'SN{sat_num:02d}'  # SN50
        
        # Get constellation (Satellogic uses "Aleph1")
        metadata['constellation'] = properties.get('constellation', 'Aleph-1')
        
        # Get platform
        metadata['platform'] = properties.get('platform', 'NewSat')
        
        # Get resolution (GSD)
        metadata['resolution'] = properties.get('gsd')
        
        # Get product level
        metadata['product_level'] = properties.get('satl:product_name', 'L1D')
        
    except Exception as e:
        print(f"Warning: Could not parse Satellogic STAC {geojson_path}: {e}")
    
    return metadata


def find_satellogic_stac(directory, filename):
    """
    Find the Satellogic STAC GeoJSON file for a given image filename.
    
    Example:
        TIF:  20241111_034238_SN50_L1D_MS_CLOUD_0.tif
        STAC: 20241111_034238_SN50_L1D_MS_metadata_stac.geojson
    
    Returns:
        str: Path to STAC GeoJSON file or None if not found
    """
    # Remove tile suffix and extension
    base_filename = os.path.basename(filename)
    base_filename = re.sub(r'_CLOUD_\d+\.tif$', '', base_filename, flags=re.IGNORECASE)
    base_filename = re.sub(r'_\d+\.tif$', '', base_filename, flags=re.IGNORECASE)
    base_filename = base_filename.replace('.tif', '').replace('.TIF', '')
    
    # Try common STAC naming patterns
    possible_stac_names = [
        f"{base_filename}_metadata_stac.geojson",
        f"{base_filename}_stac.geojson",
        f"{base_filename}.geojson"
    ]
    
    for stac_name in possible_stac_names:
        stac_path = os.path.join(directory, stac_name)
        if os.path.exists(stac_path):
            return stac_path
    
    # Try parent directory
    parent_dir = os.path.dirname(directory)
    for stac_name in possible_stac_names:
        stac_path = os.path.join(parent_dir, stac_name)
        if os.path.exists(stac_path):
            return stac_path
    
    return None

def parse_legion_xml_for_sensor(xml_path):
    """
    Extract specific Legion satellite identifier (LG01-LG06) from XML metadata.
    Returns sensor in LG0# format.
    """
    import xml.etree.ElementTree as ET
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Priority 1: Check SATID tag first (as per your memory)
        for tag_name in ['SATID', 'satId', 'SatId']:
            elements = root.findall(f".//{tag_name}")
            for elem in elements:
                if elem.text:
                    text = elem.text.strip().upper()
                    # Look for LG## pattern
                    lg_match = re.search(r'LG0?([1-6])', text)
                    if lg_match:
                        sat_num = lg_match.group(1)
                        return f'LG0{sat_num}'  # Return in LG0# format
        
        # Priority 2: Search other common sensor tags
        for tag_name in ['satelliteId', 'SATELLITEID', 'platformName', 
                        'PLATFORMNAME', 'mission', 'MISSION', 'sensor', 'SENSOR']:
            elements = root.findall(f".//{tag_name}")
            for elem in elements:
                if elem.text:
                    text = elem.text.strip().upper()
                    lg_match = re.search(r'LG0?([1-6])', text)
                    if lg_match:
                        sat_num = lg_match.group(1)
                        return f'LG0{sat_num}'
        
        # If no LG pattern found, return generic
        return 'Legion'
        
    except Exception as e:
        print(f"  ✗ Error parsing Legion XML {xml_path}: {e}")
        return 'Legion'

def find_legion_xml(directory, filename):
    """
    Find the Legion XML file for a given image filename.
    Legion XMLs are acquisition-level (no tile info), while TIFs are tile-specific.
    
    Example:
        TIF:  25JUN08220602-M2AS_R3C2-200008787224_01_P001.TIF
        XML:  25JUN08220602-M2AS_200008787224_01_P001.XML
    
    Returns:
        str: Path to XML file or None if not found
    """
    import re
    
    # Remove file extension and path
    base_filename = os.path.basename(filename)
    
    # Remove .TIF/.tif extension
    base_filename = base_filename.replace('.TIF', '').replace('.tif', '')
    
    # Remove tile info (R#C#) from the filename
    # Pattern: anything like _R3C2- or _R03C02-
    base_without_tile = re.sub(r'_R\d+C\d+-', '_', base_filename)
    # Also handle format without dash: _R3C2_
    base_without_tile = re.sub(r'_R\d+C\d+_', '_', base_without_tile)
    
    # Try different XML naming patterns
    possible_xml_names = [
        f"{base_without_tile}.XML",
        f"{base_without_tile}.xml",
        # Some vendors use DIM_ prefix
        f"DIM_{base_without_tile}.XML",
        f"DIM_{base_without_tile}.xml"
    ]
    
    for xml_name in possible_xml_names:
        xml_path = os.path.join(directory, xml_name)
        if os.path.exists(xml_path):
            return xml_path
    
    # Try looking in parent directory
    parent_dir = os.path.dirname(directory)
    for xml_name in possible_xml_names:
        xml_path = os.path.join(parent_dir, xml_name)
        if os.path.exists(xml_path):
            return xml_path
    
    return None

def parse_pixxel_xml_for_sensor(xml_path):
    """
    Parse Pixxel-specific XML to extract satellite ID and other metadata.
    
    Pixxel XML format:
    <Satellite_Id>Pixxel-FF01</Satellite_Id>
    <Order_Id>0000002227</Order_Id>
    <Processing_Level>L1C</Processing_Level>
    
    Returns:
        dict: Metadata extracted from XML
    """
    if not os.path.exists(xml_path):
        return None
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        metadata = {
            'sensor': None,
            'catid': None,
            'product_level': None,
            'satellite_id_raw': None  # Store raw value like "Pixxel-FF01"
        }
        
        # Extract Satellite_Id (e.g., "Pixxel-FF01")
        for tag in ['.//Satellite_Id', './/satelliteId', './/SATELLITE_ID']:
            elem = root.find(tag)
            if elem is not None and elem.text:
                sat_id = elem.text.strip()
                metadata['satellite_id_raw'] = sat_id
                
                # Extract FF01, FF02, etc. from "Pixxel-FF01"
                ff_match = re.search(r'FF0?([1-6])', sat_id.upper())
                if ff_match:
                    metadata['sensor'] = f"FF0{ff_match.group(1)}"
                break
        
        # Extract Order_Id (catalog ID)
        for tag in ['.//Order_Id', './/orderId', './/ORDER_ID', './/Scene_Id', './/sceneId']:
            elem = root.find(tag)
            if elem is not None and elem.text:
                metadata['catid'] = elem.text.strip()
                break
        
        # Extract Processing_Level (L1C, L2A, etc.)
        for tag in ['.//Processing_Level', './/processingLevel', './/PROCESSING_LEVEL', 
                    './/Product_Level', './/productLevel']:
            elem = root.find(tag)
            if elem is not None and elem.text:
                metadata['product_level'] = elem.text.strip()
                break
        
        return metadata
        
    except Exception as e:
        print(f"Error parsing Pixxel XML {xml_path}: {e}")
        return None

def find_pixxel_xml(directory, filename):
    """
    Find the Pixxel XML file for a given image filename.
    
    Example:
        TIF: FF01_20251014_00501045_0000002227_L1C.tif
        XML: FF01_20251014_00501045_0000002227_L1C.xml
    
    Returns:
        str: Path to XML file or None if not found
    """
    base_filename = os.path.basename(filename)
    base_name = os.path.splitext(base_filename)[0]
    
    # Try exact match with .xml extension
    xml_path = os.path.join(directory, f"{base_name}.xml")
    if os.path.exists(xml_path):
        return xml_path
    
    # Try uppercase .XML
    xml_path = os.path.join(directory, f"{base_name}.XML")
    if os.path.exists(xml_path):
        return xml_path
    
    # Try parent directory
    parent_dir = os.path.dirname(directory)
    xml_path = os.path.join(parent_dir, f"{base_name}.xml")
    if os.path.exists(xml_path):
        return xml_path
    
    return None
        
def parse_xml_metadata(xml_path):
    """
    Extract metadata from various XML formats.
    
    Returns:
        dict: metadata fields
    """
    import xml.etree.ElementTree as ET
    
    metadata = {
        'sensor': None,
        'catid': None,
        'image_type': None,
        'constellation': None,
        'affiliation': None,
        'product_level': 'NA',
        'xml_format': None
    }
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        root_tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag
        
        # Check for Legion first (priority)
        for tag in ['.//SATID', './/satId']:
            elem = root.find(tag)
            if elem is not None and elem.text:
                sensor_text = elem.text.strip().upper()
                if re.search(r'LG0[1-6]', sensor_text) or 'LEGION' in sensor_text:
                    metadata['xml_format'] = 'IMD_Legion'
                    metadata['affiliation'] = 'Maxar'
                    metadata['constellation'] = 'Legion'
                    
                    lg_match = re.search(r'LG0([1-6])', sensor_text)
                    if lg_match:
                        metadata['sensor'] = f"LG0{lg_match.group(1)}"
                    else:
                        metadata['sensor'] = 'Legion'
                    break
        
        # If not Legion, check for Pixxel
        if metadata['xml_format'] != 'IMD_Legion':
            # Check for Pixxel format
            satellite_id = root.find('.//Satellite_Id')
            if satellite_id is not None and 'PIXXEL' in satellite_id.text.upper():
                metadata['xml_format'] = 'Pixxel'
                metadata['affiliation'] = 'Pixxel'
                metadata['constellation'] = 'Firefly'
                
                # Extract specific satellite (FF01, FF02, etc.)
                sat_text = satellite_id.text.strip()
                ff_match = re.search(r'FF0?([1-6])', sat_text.upper())
                if ff_match:
                    metadata['sensor'] = f"FF0{ff_match.group(1)}"
                else:
                    metadata['sensor'] = 'Pixxel'
                
                # Extract catalog ID / Order ID
                for tag in ['.//Order_Id', './/orderId', './/Scene_Id', './/sceneId']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        metadata['catid'] = elem.text.strip()
                        break
                
                # Pixxel is always multispectral hyperspectral
                metadata['image_type'] = 'MS'
                
                # Extract product level (L1C, L2A, etc.)
                for tag in ['.//Processing_Level', './/processingLevel', './/Product_Level']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        metadata['product_level'] = elem.text.strip()
                        break
        
        # If not Pixxel or Legion, check format
        if metadata['xml_format'] not in ['IMD_Legion', 'Pixxel']:
            # Airbus DIMAP format
            if 'DIMAP' in root_tag:
                metadata['xml_format'] = 'DIMAP'
                metadata['affiliation'] = 'Airbus'
                
                # Extract sensor/mission info - THIS IS THE KEY PART
                # Look for MISSION_INDEX or MISSION tag
                mission_elem = root.find('.//MISSION_INDEX')
                if mission_elem is None:
                    mission_elem = root.find('.//MISSION')
                
                if mission_elem is not None and mission_elem.text:
                    mission = mission_elem.text.strip()
                    
                    # Extract constellation and specific sensor
                    if 'SPOT' in mission.upper():
                        metadata['constellation'] = 'SPOT'
                        # Extract number (e.g., "SPOT 6" or "SPOT6")
                        spot_match = re.search(r'SPOT\s*([67])', mission.upper())
                        if spot_match:
                            metadata['sensor'] = f"SPOT{spot_match.group(1)}"
                        else:
                            metadata['sensor'] = 'SPOT'
                    
                    elif 'PHR' in mission.upper() or 'PLEIADES' in mission.upper():
                        metadata['constellation'] = 'Pleiades'
                        # Extract PHR1A, PHR1B, PHR2A, PHR2B
                        phr_match = re.search(r'PHR\s*([12][AB])', mission.upper())
                        if phr_match:
                            metadata['sensor'] = f"PHR{phr_match.group(1)}"
                        else:
                            metadata['sensor'] = 'Pleiades'
                    
                    elif 'PNEO' in mission.upper():
                        metadata['constellation'] = 'Pleiades Neo'
                        pneo_match = re.search(r'PNEO\s*([1-4])', mission.upper())
                        if pneo_match:
                            metadata['sensor'] = f"PNEO{pneo_match.group(1)}"
                        else:
                            metadata['sensor'] = 'Pleiades Neo'
                
                # If MISSION_INDEX didn't work, try Dataset_Sources
                if not metadata['sensor']:
                    sources = root.findall('.//Dataset_Sources/Source_Information')
                    for source in sources:
                        scene_source = source.find('.//Scene_Source')
                        if scene_source is not None and scene_source.text:
                            mission = scene_source.text.strip()
                            if 'SPOT' in mission.upper():
                                metadata['constellation'] = 'SPOT'
                                spot_match = re.search(r'SPOT\s*([67])', mission.upper())
                                if spot_match:
                                    metadata['sensor'] = f"SPOT{spot_match.group(1)}"
                                else:
                                    metadata['sensor'] = 'SPOT'
                                break
                
                # Extract catalog ID
                for tag in ['.//DATASET_NAME', './/JOB_ID', './/imageId']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        metadata['catid'] = elem.text.strip()
                        break
                
                # Extract band info
                for tag in ['.//NBANDS', './/numBands']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        try:
                            num_bands = int(elem.text)
                            metadata['image_type'] = 'P' if num_bands == 1 else 'MS'
                        except:
                            pass
                        break
            
            # Maxar IMD format (non-Legion)
            elif root_tag in ['IMD', 'IMAGE_METADATA']:
                metadata['xml_format'] = 'IMD'
                metadata['affiliation'] = 'Maxar'
                
                # Extract sensor
                for tag in ['.//SATID', './/satelliteId', './/platformName']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        metadata['sensor'] = elem.text.strip()
                        break
                
                # Extract catalog ID
                for tag in ['.//CATID', './/catalogId', './/imageId']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        metadata['catid'] = elem.text.strip()
                        break
                
                # Extract band info
                for tag in ['.//NUMBANDS', './/numBands']:
                    elem = root.find(tag)
                    if elem is not None and elem.text:
                        try:
                            num_bands = int(elem.text)
                            metadata['image_type'] = 'P' if num_bands == 1 else 'MS'
                        except:
                            pass
                        break
        
        # Use lookup table to fill in missing affiliation/constellation
        if metadata['sensor'] and not metadata['constellation']:
            lookup_result = query_sensor_lookup(metadata['sensor'])
            if lookup_result['confidence'] != 'none':
                if not metadata['affiliation']:
                    metadata['affiliation'] = lookup_result['affiliation']
                if not metadata['constellation']:
                    metadata['constellation'] = lookup_result['constellation']
                    
    except Exception as e:
        print(f"Warning: Could not parse XML {xml_path}: {e}")
    
    return metadata

def standardize_legion_sensor_name(sensor_name):
    """
    Standardize Legion sensor names to LG0# format.
    Converts various formats to standard LG01-LG06.
    """
    if not sensor_name or sensor_name == 'Unknown':
        return sensor_name
    
    sensor_upper = str(sensor_name).upper()
    
    # Already in LG0# format
    if re.match(r'^LG0[1-6]$', sensor_upper):
        return sensor_upper
    
    # Convert LEGION1-6 to LG01-06
    legion_match = re.search(r'LEGION[-_\s]*([1-6])', sensor_upper)
    if legion_match:
        sat_num = legion_match.group(1)
        return f'LG0{sat_num}'
    
    # If just 'LEGION', keep it
    if sensor_upper == 'LEGION':
        return 'Legion'
    
    return sensor_name

def clean_sensor_name(sensor_string):
    """
    Remove product codes from sensor string to get clean sensor name.
    
    Parameters:
    -----------
    sensor_string : str
        Raw sensor string that might contain product codes
    
    Returns:
    --------
    str: Cleaned sensor name
    """
    if not sensor_string or sensor_string == 'Unknown':
        return sensor_string
    
    sensor_upper = str(sensor_string).upper()
    
    # Remove product codes
    for code in PRODUCT_CODES:
        sensor_upper = sensor_upper.replace(f'_{code}', '').replace(f'-{code}', '')
    
    # Extract actual sensor pattern
    sensor_patterns = [
        # Airbus patterns
        r'PNEO[1-9]', r'PHR[12][AB]', r'SPOT[67]',
        # Maxar patterns  
        r'WV0[1-4]', r'GE0[1-9]', r'QB0[1-9]',
        # Planet patterns
        r'SKYSAT', r'PS2',
        # Sentinel patterns
        r'S2[AB]',
        # Landsat patterns
        r'LC0[89]', r'LE0[789]'
    ]
    
    for pattern in sensor_patterns:
        match = re.search(pattern, sensor_upper)
        if match:
            return match.group(0)
    
    # If no pattern matches, return original cleaned string
    return sensor_upper.strip('_- ')


def parse_xml_metadata(xml_path):
    """
    Extract metadata from XML files (Airbus DIMAP, Maxar IMD, etc.)
    Enhanced to handle multiple vendor formats.
    
    Returns:
        dict: Metadata including sensor, catid, image_type, etc.
    """
    metadata = {
        'sensor': None,
        'catid': None,
        'image_type': None,
        'constellation': None,
        'affiliation': None,
        'product_level': None,
        'xml_format': None
    }
    
    if not os.path.exists(xml_path):
        return metadata
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Detect XML format
        root_tag = root.tag.upper()
        
        # Airbus DIMAP format
        if 'DIMAP' in root_tag:
            metadata['xml_format'] = 'DIMAP'
            
            # Extract mission/sensor
            for tag in ['.//MISSION', './/INSTRUMENT', './/MISSION_INDEX']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    metadata['sensor'] = elem.text.strip()
                    break
            
            # Extract product level
            for tag in ['.//PRODUCT_TYPE', './/PROCESSING_LEVEL']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    metadata['product_level'] = elem.text.strip()
                    break
            
            # Extract image type
            spectral = root.find('.//SPECTRAL_PROCESSING')
            if spectral is not None and spectral.text:
                spec_text = spectral.text.upper()
                if 'PAN' in spec_text:
                    metadata['image_type'] = 'P'
                elif 'MS' in spec_text or 'MULTI' in spec_text:
                    metadata['image_type'] = 'MS'
            
            # Check band count
            nbands = root.find('.//NBANDS')
            if nbands is not None:
                try:
                    num_bands = int(nbands.text)
                    if num_bands == 1:
                        metadata['image_type'] = 'P'
                    elif num_bands > 1:
                        metadata['image_type'] = 'MS'
                except:
                    pass
            
            # Extract catalog ID
            for tag in ['.//DATASET_NAME', './/JOB_ID', './/DATASET_ID']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    metadata['catid'] = elem.text.strip()
                    break
        
        # Maxar IMD format
        elif root_tag in ['IMD', 'IMAGE_METADATA']:
            metadata['xml_format'] = 'IMD'
            
            # Extract sensor
            for tag in ['.//SATID', './/satelliteId', './/SENSOR']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    metadata['sensor'] = elem.text.strip()
                    break
            
            # Extract catalog ID
            for tag in ['.//CATID', './/catalogId', './/imageId']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    metadata['catid'] = elem.text.strip()
                    break
            
            # Extract band info
            for tag in ['.//NUMBANDS', './/numBands', './/bandId']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    try:
                        num_bands = int(elem.text)
                        metadata['image_type'] = 'P' if num_bands == 1 else 'MS'
                    except:
                        pass
                    break
        
        # Use lookup table to fill in affiliation/constellation from sensor
        if metadata['sensor']:
            lookup_result = query_sensor_lookup(metadata['sensor'])
            if lookup_result['confidence'] != 'none':
                if not metadata['affiliation']:
                    metadata['affiliation'] = lookup_result['affiliation']
                if not metadata['constellation']:
                    metadata['constellation'] = lookup_result['constellation']
                    
    except Exception as e:
        print(f"Warning: Could not parse XML {xml_path}: {e}")
    
    return metadata

def standardize_attributes(row):
    """
    Post-processing cleanup to standardize attribute values.
    Uses lookup table for validation.
    
    Returns:
        dict: cleaned attributes
    """
    cleaned = row.copy()
    lookup_table = load_sensor_lookup()
    
    # Clean sensor name (remove product codes)
    if 'sensor' in cleaned and pd.notna(cleaned['sensor']):
        sensor = str(cleaned['sensor'])
        
        # Standardize Legion names
        if 'LEGION' in sensor.upper() or re.search(r'LG0[1-6]', sensor.upper()):
            cleaned['sensor'] = standardize_legion_sensor_name(sensor)
        else:
            cleaned['sensor'] = clean_sensor_name(sensor)
    
    # Standardize image_type
    current_img_type = cleaned.get('image_type', 'Unknown')
    if current_img_type not in ['P', 'MS']:
        img_type_str = str(current_img_type).upper() if pd.notna(current_img_type) else ''
        
        for img_type, patterns in IMAGE_TYPE_PATTERNS.items():
            if any(pattern in img_type_str for pattern in patterns):
                cleaned['image_type'] = img_type
                break
        
        # If still unknown, try sensor or directory context
        if cleaned.get('image_type') not in ['P', 'MS']:
            sensor_str = str(cleaned.get('sensor', '')).upper() if pd.notna(cleaned.get('sensor')) else ''
            #print(f'\n Cleaned sensor string: {sensor_str}\n')
            if any(p in sensor_str for p in ['P3DS', 'PAN']):
                cleaned['image_type'] = 'P'
            elif any(p in sensor_str for p in ['M3DS', 'MS', 'MULTI']):
                cleaned['image_type'] = 'MS'
            else:
                cleaned['image_type'] = 'Unknown still'
    
    # Validate and standardize affiliation using lookup table
    sensor = str(cleaned.get('sensor', '')) if pd.notna(cleaned.get('sensor')) else ''
    current_affiliation = cleaned.get('affiliation', 'Unknown')
    
    # If affiliation is unknown or suspicious, query lookup table
    if current_affiliation == 'Unknown' or current_affiliation in PRODUCT_CODES:
        if sensor:
            lookup_result = query_sensor_lookup(sensor, lookup_table)
            if lookup_result['confidence'] != 'none':
                cleaned['affiliation'] = lookup_result['affiliation']
                if cleaned.get('constellation', 'Unknown') == 'Unknown':
                    cleaned['constellation'] = lookup_result['constellation']
    
    # Ensure constellation matches affiliationconstellation
    if cleaned.get('affiliation') != 'Unknown' and cleaned.get('sensor') != 'Unknown':
        if sensor:
            # Query lookup to ensure consistency
            lookup_result = query_sensor_lookup(sensor, lookup_table)
            if lookup_result['confidence'] != 'none':
                # Override with authoritative lookup data
                cleaned['affiliation'] = lookup_result['affiliation']
                cleaned['constellation'] = lookup_result['constellation']
    
    return cleaned

# Update get_attributes_from_filename() to use this for Legion:
def get_attributes_from_filename(footprint_gdf, image_type, file_split_str='.'):
    """
    Enhanced attribute extraction using multi-source approach with lookup table.
    Priority: XML metadata > Directory structure > Filename parsing > Lookup table validation
    """
    import re
    
    # Load lookup table
    lookup_table = load_sensor_lookup()
    
    # Clean filenames
    footprint_gdf['cleaned_filename'] = (footprint_gdf['file']
                                         .str.replace('.TIF', '', regex=False)
                                         .str.replace('.tif', '', regex=False)
                                         .str.replace('.JP2', '', regex=False)
                                         .str.replace('.jp2', '', regex=False)
                                         .str.replace('IMG_', '', regex=False))
    
    # Initialize columns with safe defaults
    footprint_gdf['affiliation'] = 'Unknown'
    footprint_gdf['constellation'] = 'Unknown'
    footprint_gdf['sensor'] = 'Unknown'
    footprint_gdf['image_type'] = 'Unknown'
    footprint_gdf['catid'] = 'unknown'
    footprint_gdf['product_level'] = 'Unknown'
    footprint_gdf['confidence'] = 'none'
    
    # Track file extension explicitly
    footprint_gdf['source_type'] = footprint_gdf['file'].str.split('.').str[-1].str.upper()
    
    print("Extracting attributes from multiple sources...")
    print(f"Using sensor lookup table with {len(lookup_table)} satellite systems")
    
    for idx, row in footprint_gdf.iterrows():
        filepath = os.path.join(row['path'], row['file'])
        directory = row['path']
        filename = row['cleaned_filename']
        
        # Step 0: Check for Legion first (has unique format)
        # First detect with original filename
        legion_result = detect_legion_sensor(filepath, filename)
        if legion_result:
            # NOW remove tile pattern for Legion XML matching
            base_filename_no_tile = re.sub(r'_R\d+C\d+', '', filename)
            base_filename_no_tile = re.sub(r'-R\d+C\d+', '', base_filename_no_tile)
            
            footprint_gdf.at[idx, 'affiliation'] = legion_result['affiliation']
            footprint_gdf.at[idx, 'constellation'] = legion_result['constellation']
            footprint_gdf.at[idx, 'sensor'] = legion_result['sensor']  # Default to 'Legion'
            footprint_gdf.at[idx, 'confidence'] = legion_result['confidence']
            
            # Try to get specific satellite from XML using base filename (no tile info)
            legion_xml = find_legion_xml(directory, base_filename_no_tile)
            if legion_xml:
                legion_sensor = parse_legion_xml_for_sensor(legion_xml)
                if legion_sensor and legion_sensor != 'Legion':
                    footprint_gdf.at[idx, 'sensor'] = legion_sensor
                    footprint_gdf.at[idx, 'confidence'] = 'high'
            
            if 'image_type' in legion_result:
                footprint_gdf.at[idx, 'image_type'] = legion_result['image_type']
            
            # Try to extract catid from Legion filename format (use original filename)
            catid_match = re.search(r'-(\d+)_\d+_P\d+', filename)
            if catid_match:
                footprint_gdf.at[idx, 'catid'] = catid_match.group(1)
            
            continue  # Skip to next file
            
        # Step 0.5: Check for Satellogic (uses STAC metadata)
        if '_SN' in filename or 'NEWSAT' in filename.upper():
            # Try to find STAC GeoJSON
            stac_file = find_satellogic_stac(directory, row['file'])
            if stac_file:
                stac_metadata = parse_satellogic_stac(stac_file)
                if stac_metadata.get('sensor'):
                    footprint_gdf.at[idx, 'affiliation'] = 'Satellogic'
                    footprint_gdf.at[idx, 'constellation'] = stac_metadata['constellation']
                    footprint_gdf.at[idx, 'sensor'] = stac_metadata['sensor']
                    footprint_gdf.at[idx, 'confidence'] = 'high'
                    footprint_gdf.at[idx, 'image_type'] = 'MS'
                    footprint_gdf.at[idx, 'product_level'] = stac_metadata.get('product_level', 'L1D')
                    continue  # Skip to next file
                    
        # Step 1: Try to find and parse XML metadata (for non-Legion)
        # Use ORIGINAL filename for non-Legion files
        xml_metadata = {}
        base_name = filename.split('_R')[0] if '_R' in filename else filename
        possible_xml_patterns = [
            os.path.join(directory, f"{base_name}.XML"),
            os.path.join(directory, f"{base_name}.xml"),
            os.path.join(directory, f"DIM_{base_name}.XML"),
            os.path.join(directory, f"{row['file'].replace('.TIF', '.XML').replace('.tif', '.xml').replace('.JP2', '.XML').replace('.jp2', '.xml')}")
        ]
        
        for xml_pattern in possible_xml_patterns:
            if os.path.exists(xml_pattern):
                xml_metadata = parse_xml_metadata(xml_pattern)
                if xml_metadata.get('sensor'):
                    break
        
        # Step 2: Infer from directory structure
        dir_info = infer_from_directory_path(filepath, lookup_table)
        
        # Step 3: Parse from filename
        file_info = parse_sensor_from_filename(filename, lookup_table)
        
        # Step 4: Parse image type
        imgtype_from_file = parse_image_type_from_filename(filename, directory)
        
        # Combine information with priority: XML > Directory > Filename
        # Affiliation
        if xml_metadata.get('affiliation'):
            footprint_gdf.at[idx, 'affiliation'] = xml_metadata['affiliation']
            footprint_gdf.at[idx, 'confidence'] = 'high'
        elif dir_info.get('confidence') == 'high':
            footprint_gdf.at[idx, 'affiliation'] = dir_info['affiliation']
            footprint_gdf.at[idx, 'confidence'] = 'high'
        elif file_info.get('confidence') != 'none':
            footprint_gdf.at[idx, 'affiliation'] = file_info['affiliation']
            footprint_gdf.at[idx, 'confidence'] = file_info['confidence']
        
        # Constellation
        if xml_metadata.get('constellation'):
            footprint_gdf.at[idx, 'constellation'] = xml_metadata['constellation']
        elif dir_info.get('confidence') == 'high':
            footprint_gdf.at[idx, 'constellation'] = dir_info['constellation']
        elif file_info.get('confidence') != 'none':
            footprint_gdf.at[idx, 'constellation'] = file_info['constellation']
        
        # Sensor - Prefer more specific sensor information
        xml_sensor = xml_metadata.get('sensor')
        file_sensor = file_info.get('sensor', 'Unknown')
        dir_sensor = dir_info.get('sensor', 'Unknown')
        
        # Choose most specific sensor
        if xml_sensor and file_sensor != 'Unknown':
            # If filename has more specific info (e.g., SPOT6 vs SPOT), use filename
            if len(file_sensor) > len(xml_sensor) and xml_sensor in file_sensor:
                footprint_gdf.at[idx, 'sensor'] = file_sensor
            else:
                footprint_gdf.at[idx, 'sensor'] = xml_sensor
        elif xml_sensor:
            footprint_gdf.at[idx, 'sensor'] = xml_sensor
        elif file_sensor != 'Unknown':
            footprint_gdf.at[idx, 'sensor'] = file_sensor
        elif dir_sensor != 'Unknown':
            footprint_gdf.at[idx, 'sensor'] = dir_sensor
        
        # Image type
        if xml_metadata.get('image_type'):
            footprint_gdf.at[idx, 'image_type'] = xml_metadata['image_type']
        else:
            footprint_gdf.at[idx, 'image_type'] = imgtype_from_file
        
        # Catalog ID from XML or filename
        if xml_metadata.get('catid'):
            footprint_gdf.at[idx, 'catid'] = xml_metadata['catid']
        else:
            # Try to extract from various filename patterns
            # Pattern 1: Standard format with catid
            catid_match = re.search(r'_(\d{10,})_', filename)
            if catid_match:
                footprint_gdf.at[idx, 'catid'] = catid_match.group(1)
        
        # Product level from XML
        if xml_metadata.get('product_level'):
            footprint_gdf.at[idx, 'product_level'] = xml_metadata['product_level']
    
    # Step 5: Apply standardization and cleanup
    print("Standardizing attributes...")
    cleaned_rows = []
    for idx, row in footprint_gdf.iterrows():
        cleaned = standardize_attributes(row)
        cleaned_rows.append(cleaned)
    
    # Update dataframe with cleaned attributes
    for col in ['affiliation', 'constellation', 'sensor', 'image_type']:
        if col in cleaned_rows[0]:  # Make sure the column exists
            footprint_gdf[col] = [r[col] for r in cleaned_rows]
    
    # Add date parsing and base_image_name (keep existing logic from your code)
    footprint_gdf = add_date_attributes(footprint_gdf)
    footprint_gdf = add_base_image_name(footprint_gdf, file_split_str)
    
    # Report on attribute quality
    print("\n=== Attribute Extraction Summary ===")
    print(f"\nAffiliations found:")
    print(footprint_gdf['affiliation'].value_counts().to_dict())
    print(f"\nConstellations found:")
    print(footprint_gdf['constellation'].value_counts().to_dict())
    print(f"\nImage Types:")
    print(footprint_gdf['image_type'].value_counts().to_dict())
    print(f"\nUnique Sensors: {footprint_gdf['sensor'].nunique()}")
    print(footprint_gdf['sensor'].value_counts().head(10))
    
    # Confidence report
    print(f"\nConfidence levels:")
    print(footprint_gdf['confidence'].value_counts().to_dict())
    
    # Flag potential issues
    unknown_aff = (footprint_gdf['affiliation'] == 'Unknown').sum()
    unknown_sensor = (footprint_gdf['sensor'] == 'Unknown').sum()
    unknown_imgtype = (footprint_gdf['image_type'] == 'Unknown').sum()
    
    if unknown_aff > 0 or unknown_sensor > 0 or unknown_imgtype > 0:
        print(f"\n⚠️  Issues found:")
        if unknown_aff > 0:
            print(f"   - {unknown_aff} files with Unknown affiliation")
        if unknown_sensor > 0:
            print(f"   - {unknown_sensor} files with Unknown sensor")
        if unknown_imgtype > 0:
            print(f"   - {unknown_imgtype} files with Unknown image_type")
        
        print("\nSample problematic files:")
        problem_df = footprint_gdf[
            (footprint_gdf['affiliation'] == 'Unknown') |
            (footprint_gdf['sensor'] == 'Unknown') |
            (footprint_gdf['image_type'] == 'Unknown')
        ]
        if len(problem_df) > 0:
            print(problem_df[['file', 'path', 'affiliation', 'sensor', 'image_type']].head())
    else:
        print("\n✓ All files successfully attributed!")
    
    return footprint_gdf

def detect_legion_sensor(filepath, filename):
    """
    Special detection for Maxar Legion constellation.
    Legion files have format: YYMMMDDHHMMSS-[P|M]3DS_R#C#-CATID_ORDER_PRODUCT.TIF
    
    Returns:
        dict or None: Legion-specific metadata if detected
    """
    # Check for Legion patterns
    if 'Legion' in filepath or 'LEGION' in filepath.upper():
        # Try to parse the specific sensor from catalog ID or order number
        # For now, return generic Legion
        result = {
            'affiliation': 'Maxar',
            'constellation': 'Legion',
            'sensor': '',  # Could be enhanced to detect specific satellite
            'confidence': 'high'
        }
        
        # Check image type from filename
        if '-P' in filename.upper(): # -P3DS
            result['image_type'] = 'P'
        elif '-M' in filename.upper(): # -M3DS
            result['image_type'] = 'MS'
        
        return result
    
    # Check for P3DS/M3DS pattern (unique to Legion currently)
    if re.search(r'\d{2}[A-Z]{3}\d{8}-[PM]3DS_R\d+C\d+', filename):
        result = {
            'affiliation': 'Maxar',
            'constellation': 'Legion',
            'sensor': '',
            'confidence': 'high'
        }
        
        if '-P3DS' in filename.upper():
            result['image_type'] = 'P'
        elif '-M3DS' in filename.upper():
            result['image_type'] = 'MS'
        
        return result
    
    return None

def add_date_attributes(footprint_gdf):
    """
    Extract date information from filenames.
    Handles multiple date formats.
    """
    import re
    from datetime import datetime
    
    # Initialize date columns
    footprint_gdf['year'] = 1900
    footprint_gdf['month'] = 1
    footprint_gdf['day'] = 1
    footprint_gdf['date'] = pd.to_datetime('1900-01-01')
    
    month_map = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4,
        'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8,
        'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
    }
    
    for idx, row in footprint_gdf.iterrows():
        filename = row['cleaned_filename']
        
        # Try Legion/Maxar format: YYMMMDDHHMMSS (e.g., 25AUG29102055)
        legion_match = re.search(r'(\d{2})([A-Z]{3})(\d{2})\d{6}', filename)
        if legion_match:
            year_short = legion_match.group(1)
            month_str = legion_match.group(2)
            day = legion_match.group(3)
            
            year = 2000 + int(year_short)
            month = month_map.get(month_str, 1)
            day = int(day)
            
            footprint_gdf.at[idx, 'year'] = year
            footprint_gdf.at[idx, 'month'] = month
            footprint_gdf.at[idx, 'day'] = day
            
            try:
                footprint_gdf.at[idx, 'date'] = datetime(year, month, day)
            except:
                pass
            continue
        
        # Try standard format: YYYYMMDD (e.g., 20250829)
        standard_match = re.search(r'(\d{4})(\d{2})(\d{2})', filename)
        if standard_match:
            year = int(standard_match.group(1))
            month = int(standard_match.group(2))
            day = int(standard_match.group(3))
            
            # Validate date
            if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                footprint_gdf.at[idx, 'year'] = year
                footprint_gdf.at[idx, 'month'] = month
                footprint_gdf.at[idx, 'day'] = day
                
                try:
                    footprint_gdf.at[idx, 'date'] = datetime(year, month, day)
                except:
                    pass
    
    return footprint_gdf


# def add_base_image_name(footprint_gdf, file_split_str='.'):
#     """Create base image name for grouping tiles"""
#     # Keep your existing base_image_name logic
#     footprint_gdf['base_image_name'] = (footprint_gdf['cleaned_filename']
#                                        .str.replace(r'_R\d+C\d+', '', regex=True))
#     return footprint_gdf

def add_base_image_name(footprint_gdf, file_split_str='.'):
    """
    Create base image name for grouping tiles from the same acquisition.
    Removes tile information (R#C#) to create a common identifier.
    """
    import re
    
    def create_base_name(filename):
        """Remove tile info and create base name"""
        # Remove tile patterns (R#C#, R##C##, etc.)
        base_name = re.sub(r'_R\d+C\d+', '', filename)
        base_name = re.sub(r'-R\d+C\d+', '', base_name)
        
        return base_name
    
    footprint_gdf['base_image_name'] = footprint_gdf['cleaned_filename'].apply(create_base_name)
    
    # Also create footprint_name (more human-readable, excludes processing codes)
    def create_footprint_name(row):
        """Create a cleaner footprint name"""
        base = row['base_image_name']
        
        # For Legion format, keep date-sensor-catid
        if re.search(r'\d{2}[A-Z]{3}\d{8}-[PM]3DS', base):
            # Extract just the essential parts
            match = re.search(r'(\d{2}[A-Z]{3}\d{2})-([PM]3DS)-(\d+)', base)
            if match:
                date_part = match.group(1)
                sensor_part = match.group(2)
                catid = match.group(3)
                return f"{date_part}-{sensor_part}-{catid}"
        
        return base
    
    footprint_gdf['footprint_name'] = footprint_gdf.apply(create_footprint_name, axis=1)
    
    return footprint_gdf
    
###################################
###################################
###################################

def parse_sensor_from_filename_safe(filename):
    """
    Safe wrapper for parsing sensor info from filename.
    Returns a dict with all expected keys, using defaults for missing values.
    
    Parameters:
    -----------
    filename : str
        Filename to parse
    
    Returns:
    --------
    dict: sensor info with guaranteed keys
    """
    import re
    
    # Initialize with safe defaults
    sensor_info = {
        'sensor': 'Unknown',
        'catid': 'unknown',
        'image_type': 'Unknown',
        'date_str': '19000101',
        'time_str': '000000',
        'tile': '',
        'base_image_name': filename,
        'year': 1900,
        'month': 1,
        'day': 1,
        'source_type': 'Unknown'  # Add this
    }
    
    # Extract file extension for source_type
    if '.' in filename:
        ext = filename.split('.')[-1].upper()
        sensor_info['source_type'] = ext
    
    # Try to call the lookup-based parser
    try:
        lookup_result = parse_sensor_from_filename(filename)
        if lookup_result and isinstance(lookup_result, dict):
            # Merge results, keeping defaults for missing keys
            for key in sensor_info.keys():
                if key in lookup_result and lookup_result[key] is not None:
                    sensor_info[key] = lookup_result[key]
    except Exception as e:
        print(f"Warning: Could not parse filename {filename}: {e}")
    
    # Additional parsing for catid and other fields from filename
    filename_clean = filename.replace('.TIF', '').replace('.tif', '').replace('.JP2', '').replace('.jp2', '')
    
    # Try to extract catid from various patterns
    # Pattern 1: Legion format YYMMMDDHHMMSS-[P|M]3DS_R#C#-CATID_ORDER_PRODUCT
    catid_match = re.search(r'-(\d{12,15})_\d+_P\d+', filename_clean)
    if catid_match:
        sensor_info['catid'] = catid_match.group(1)
    else:
        # Pattern 2: Standard _CATID_ pattern
        catid_match = re.search(r'_(\d{10,15})_', filename_clean)
        if catid_match:
            sensor_info['catid'] = catid_match.group(1)
        else:
            # Pattern 3: CATID at end before tile
            catid_match = re.search(r'_(\d{10,15})(?:_R\d+C\d+)?$', filename_clean)
            if catid_match:
                sensor_info['catid'] = catid_match.group(1)
    
    # Extract tile information
    tile_match = re.search(r'_R(\d+)C(\d+)', filename_clean)
    if tile_match:
        sensor_info['tile'] = f"R{tile_match.group(1)}C{tile_match.group(2)}"
    
    # Create base image name (without tile info)
    base_name = re.sub(r'_R\d+C\d+', '', filename_clean)
    sensor_info['base_image_name'] = base_name
    
    return sensor_info


def footprint_gpkg_wrapper_with_tracking(f_list, d, OUT_FOOT_FN, WRITE_GPKG=False):
    """
    Enhanced wrapper that tracks failed footprint operations.
    
    Returns:
    --------
    tuple: (footprint_gdf, failed_files_df, failed_acquisitions_df)
    """
    from multiprocessing import Pool
    from functools import partial
    import re
    
    print(f"\nProcessing {len(f_list)} files...")
    
    # Process footprints with error tracking
    with Pool(processes=4) as pool:  # Adjust processes as needed
        results = pool.map(
            partial(
                    footprintlib.raster_footprint, # no
                    #footprintlib.raster_footprint_with_til_support,
                   DO_DATAMASK=False, 
                   GET_ONLY_DATASETMASK=False, 
                   R_READ_MODE='r', 
                   MANY_CRS=True), 
            f_list
        )
    
    # Separate successful and failed results
    successful_gdfs = []
    failed_files = []
    
    for idx, result in enumerate(results):
        if result is not None:
            successful_gdfs.append(result)
        else:
            failed_files.append(f_list[idx])
    
    print(f"Successfully footprinted: {len(successful_gdfs)} files")
    print(f"Failed to footprint: {len(failed_files)} files")
    
    # Build footprint database from successful results
    if successful_gdfs:
        footprint_gdf = footprintlib.build_footprint_db(
            successful_gdfs, 
            TO_GCS=False, 
            WRITE_GPKG=False, 
            OUT_F_NAME='', 
            OUT_LYR_NAME=d.get('TYPE_NAME', 'imagery'), 
            DROP_DUPLICATES=True
        )
        
        # Extract attributes using the enhanced function
        footprint_gdf = get_attributes_from_filename(
            footprint_gdf, 
            d.get('TYPE_NAME', 'TIF'), 
            d.get('SPLIT_STR', '.')
        )

        # Make scene and acquisition id fields
        footprint_gdf = extract_scene_and_acquisition_ids(footprint_gdf)
        
        # Write to file if requested
        if WRITE_GPKG and OUT_FOOT_FN:
            print(f"Writing footprints to: {OUT_FOOT_FN}")
            os.makedirs(os.path.dirname(OUT_FOOT_FN), exist_ok=True)
            footprint_gdf.to_file(OUT_FOOT_FN, driver='GPKG')
    else:
        print("No successful footprints to process!")
        footprint_gdf = gpd.GeoDataFrame()
    
    # Process failed files
    COLNAMES_BASIC = ['path','sensor','source_type']
    COLNAMES_FAILED_ACQS = COLNAMES_BASIC + ['failed_tile_count','filepath']
    COLNAMES_FAILED_SCENES = COLNAMES_BASIC + ['filename','filepath','tile','base_image_name']
    if failed_files:
        print(f"\nAnalyzing {len(failed_files)} failed files...")
        failed_data = []
        
        for failed_file in failed_files:
            # Split path and filename
            path = os.path.dirname(failed_file)
            filename = os.path.basename(failed_file)
            
            # Parse filename to extract sensor info using safe wrapper
            sensor_info = parse_sensor_from_filename_safe(filename)
            
            failed_data.append({
                'path': path,
                'sensor': sensor_info['sensor'],
                'source_type': sensor_info['source_type'],  
                'filename': filename,
                'filepath': failed_file,
                'tile': sensor_info['tile'],
                'base_image_name': sensor_info['base_image_name']              
            })
        
        failed_files_df = pd.DataFrame(failed_data)
        
        # Create acquisition-level summary
        if len(failed_files_df) > 0:
            failed_acquisitions_df = failed_files_df.groupby('base_image_name').agg({
                'path': 'first',
                'sensor': 'first',
                'source_type': 'first',
                'filename': 'count',  # Count of failed tiles per acquisition
                'filepath': lambda x: list(x)  # List all failed file paths
            }).reset_index()
            
            failed_acquisitions_df.rename(columns={'filename': 'failed_tile_count'}, inplace=True)
        else:
            failed_acquisitions_df = pd.DataFrame(columns=COLNAMES_FAILED_ACQS) # Set colnames so that blank df will be written if nothing fails
        
        print(f"\n⚠️  Failed to footprint {len(failed_files)} files")
        print(f"⚠️  Representing {len(failed_acquisitions_df)} unique acquisitions")
        
        # # Show sample of failures
        # if len(failed_files_df) > 0:
        #     print("\nSample failed files:")
        #     print(failed_files_df[['filename', 'sensor', 
        #                            #'catid', 
        #                            'image_type', 'source_type']].head(10))
    else:
        failed_files_df = pd.DataFrame(columns=COLNAMES_FAILED_SCENES)
        failed_acquisitions_df = pd.DataFrame(columns=COLNAMES_FAILED_ACQS)
        print(f"\n✓ All files successfully footprinted!: {COLNAMES_FAILED_ACQS}")
    
    return footprint_gdf, failed_files_df, failed_acquisitions_df
    
def process_multiple_image_types(config_list, WRITE_GPKG=True):
    """
    Process footprints for multiple image types.
    
    Parameters:
    -----------
    config_list : list of dict
        List of configuration dictionaries, each containing:
        - MAINDIR: Main directory path
        - RUNNAME: Run name
        - SEARCH_STRING: File search pattern (e.g., '/**/*.TIF')
        - TYPE_NAME: Type identifier
        - SPLIT_STR: Split string for parsing
        - OUT_FOOT_FN: (optional) Output filename
    WRITE_GPKG : bool
        Whether to write geopackages
    
    Returns:
    --------
    tuple: (combined_footprints_gdf, all_failed_files_df, all_failed_acquisitions_df)
    """
    
    all_footprint_gdfs = []
    all_failed_files = []
    all_failed_acquisitions = []
    
    for idx, config in enumerate(config_list, 1):
        print("\n" + "="*80)
        print(f"Processing {idx}/{len(config_list)}: {config['TYPE_NAME']}")
        print("="*80)
        
        # Set target directory
        config['TARGET_DIR'] = f"{config['MAINDIR']}/{config['RUNNAME']}"
        
        # Set output filename if not provided
        if 'OUT_FOOT_FN' not in config:
            config['OUT_FOOT_FN'] = os.path.join(
                config['MAINDIR'], 
                config['RUNNAME'],
                'footprints',
                f"footprints_{config['RUNNAME'].replace('/','_')}_{config['TYPE_NAME'].replace('*','')}.gpkg"
            )
        
        # Find files
        print(f"Searching in: {config['TARGET_DIR']}")
        print(f"Pattern: {config['SEARCH_STRING']}")
        
        f_list = glob.glob(
            f"{config['TARGET_DIR']}{config['SEARCH_STRING']}", 
            recursive=True
        )
        
        print(f"Found {len(f_list)} files")
        
        if len(f_list) == 0:
            print(f"No files found for {config['TYPE_NAME']}, skipping...")
            continue
        
        # Process footprints
        footprint_gdf, failed_files_df, failed_acquisitions_df = footprint_gpkg_wrapper_with_tracking(
            f_list, 
            config, 
            config['OUT_FOOT_FN'], 
            WRITE_GPKG=WRITE_GPKG
        )
        # Preserve these for writing out empty dfs with the cols
        COLNAMES_FAILED_SCENES = failed_files_df.columns
        COLNAMES_FAILED_ACQS = failed_acquisitions_df.columns
        
        # Collect results
        if len(footprint_gdf) > 0:
            all_footprint_gdfs.append(footprint_gdf)
        if len(failed_files_df) > 0:
            all_failed_files.append(failed_files_df)
        if len(failed_acquisitions_df) > 0:
            all_failed_acquisitions.append(failed_acquisitions_df)
    
    # Combine results from all image types
    print("\n" + "="*80)
    print("Combining results from all image types...")
    print("="*80)
    
    if all_footprint_gdfs:
        combined_footprints = pd.concat(all_footprint_gdfs, ignore_index=True)
        combined_footprints = gpd.GeoDataFrame(combined_footprints, geometry='geometry')
        print(f"\nTotal footprints: {len(combined_footprints)}")
    else:
        combined_footprints = gpd.GeoDataFrame()
        print("\nNo footprints generated!")
    
    if all_failed_files:
        combined_failed_files = pd.concat(all_failed_files, ignore_index=True)
        print(f"Total failed files: {len(combined_failed_files)}")
    else:
        combined_failed_files = pd.DataFrame(columns=COLNAMES_FAILED_SCENES)
    
    if all_failed_acquisitions:
        combined_failed_acquisitions = pd.concat(all_failed_acquisitions, ignore_index=True)
        print(f"Total failed acquisitions: {len(combined_failed_acquisitions)}")
    else:
        combined_failed_acquisitions = pd.DataFrame(columns=COLNAMES_FAILED_ACQS)
    
    # Final summary
    if len(combined_footprints) > 0:
        print("\n" + "="*80)
        print("FINAL SUMMARY")
        print("="*80)
        print(f"\nTotal footprints by affiliation:")
        print(combined_footprints['affiliation'].value_counts())
        print(f"\nTotal footprints by constellation:")
        print(combined_footprints['constellation'].value_counts())
        print(f"\nTotal footprints by sensor:")
        print(combined_footprints['sensor'].value_counts())
        print(f"\nTotal footprints by image type:")
        print(combined_footprints['image_type'].value_counts())
    
    return combined_footprints, combined_failed_files, combined_failed_acquisitions

def footprint_gpkg_wrapper(f_list, d, OUT_FOOT_FN, WRITE_GPKG=False):
    
    with Pool(processes=1) as pool:
        f_gdf_lst = pool.map(partial(footprintlib.raster_footprint, DO_DATAMASK=False, GET_ONLY_DATASETMASK=False, R_READ_MODE='r', MANY_CRS=True), f_list)
        
    footprint_gdf = footprintlib.build_footprint_db(f_gdf_lst, TO_GCS=False, WRITE_GPKG=False, OUT_F_NAME='', OUT_LYR_NAME=d['TYPE_NAME'], DROP_DUPLICATES=True)
    #footprint_gdf = footprintlib.get_attributes_from_filename(footprint_gdf, d['TYPE_NAME'], d['SPLIT_STR'])
    footprint_gdf = get_attributes_from_filename(footprint_gdf, d['TYPE_NAME'], d['SPLIT_STR'])

    
    footprint_gdf['affiliation'] = footprint_gdf['path'].str.split(d['RUNNAME']+'/', expand=True)[1].str.split('/', expand=True)[0] # this could be sensitive - todo - make better
    footprint_gdf['constellation'] = footprint_gdf['path'].str.split(d['RUNNAME']+'/', expand=True)[1].str.split('/', expand=True)[1] # this could be sensitive - todo - make better

    #footprint_gdf['year_cat'] = footprint_gdf.year.astype(str)
    #footprint_gdf['month_cat'] = footprint_gdf.month.astype(str)
    print(footprint_gdf.shape)
    
    if WRITE_GPKG:
        print(d['OUT_FOOT_FN'])
        footprint_gdf.to_file(OUT_FOOT_FN, driver='GPKG')
    
    return footprint_gdf
    
# def get_crs_info(filepath):
#     """
#     Extract CRS information from a raster file.
    
#     Returns:
#         tuple: (epsg_code, crs_name, zone)
#     """
#     try:
#         with rasterio.open(filepath) as src:
#             crs = src.crs
            
#             if crs is None:
#                 return (None, 'No CRS', None)
            
#             # Get EPSG code
#             epsg_code = crs.to_epsg()
            
#             # Determine CRS name and zone
#             crs_string = crs.to_string()
#             crs_wkt = crs.to_wkt() if crs.to_wkt() else ''
            
#             # Check if it's UTM
#             if 'UTM' in crs_wkt.upper() or 'UTM' in crs_string.upper():
#                 crs_name = 'UTM'
#                 # Try to extract zone from the CRS
#                 zone = None
#                 try:
#                     # Get UTM zone from the CRS
#                     if hasattr(crs, 'utm_zone'):
#                         zone = crs.utm_zone
#                     else:
#                         # Parse from EPSG or string representation
#                         if epsg_code:
#                             # UTM North zones: 32601-32660 (WGS84), 326xx pattern
#                             # UTM South zones: 32701-32760 (WGS84), 327xx pattern
#                             if 32601 <= epsg_code <= 32660:
#                                 zone = f"{epsg_code - 32600}N"
#                             elif 32701 <= epsg_code <= 32760:
#                                 zone = f"{epsg_code - 32700}S"
#                             # Similar patterns for other datums
#                             elif 'zone' in crs_string.lower():
#                                 # Try to parse zone from string
#                                 import re
#                                 zone_match = re.search(r'zone[_\s]+(\d+)', crs_string, re.IGNORECASE)
#                                 if zone_match:
#                                     zone_num = zone_match.group(1)
#                                     # Check for hemisphere
#                                     if 'south' in crs_string.lower():
#                                         zone = f"{zone_num}S"
#                                     else:
#                                         zone = f"{zone_num}N"
#                 except Exception:
#                     zone = None
                    
#             # Check if it's WGS84 (geographic)
#             elif epsg_code == 4326 or 'WGS 84' in crs_wkt or 'WGS84' in crs_string:
#                 crs_name = 'WGS84'
#                 zone = None
                
#             # Check for other common geographic systems
#             elif 'geographic' in crs_wkt.lower() or crs.is_geographic:
#                 if 'NAD83' in crs_wkt or 'NAD83' in crs_string:
#                     crs_name = 'NAD83'
#                 elif 'NAD27' in crs_wkt or 'NAD27' in crs_string:
#                     crs_name = 'NAD27'
#                 else:
#                     crs_name = 'Geographic'
#                 zone = None
                
#             # Check for projected systems
#             elif crs.is_projected:
#                 if 'Albers' in crs_wkt:
#                     crs_name = 'Albers'
#                 elif 'Lambert' in crs_wkt:
#                     crs_name = 'Lambert'
#                 elif 'Mercator' in crs_wkt:
#                     crs_name = 'Mercator'
#                 elif 'Polar' in crs_wkt or 'Stereographic' in crs_wkt:
#                     crs_name = 'Polar Stereographic'
#                 else:
#                     crs_name = 'Projected'
#                 zone = None
#             else:
#                 crs_name = 'Other'
#                 zone = None
                
#             return (epsg_code, crs_name, zone)
            
#     except rasterio.errors.RasterioIOError as e:
#         print(f"Error reading file {filepath}: {e}")
#         return (None, 'File Error', None)
#     except Exception as e:
#         print(f"Unexpected error processing {filepath}: {e}")
#         return (None, 'Parse Error', None)

def make_CSDA_footprints_map(gdf, MAP=None, width='100%', height='25%', ACQS=True, site_name_col='Primary_Site'):

    Map_Figure=Figure()
    
    if MAP is None:
        
        #------------------
        m = Map(
            width=width,height=height,
            #tiles="Stamen Toner",
            #tiles=None,
            #location=(60, 5),
            #zoom_start=3, 
            control_scale = True
        )
        
    else:
        m = MAP
        
    TOOLTIP_FIELDS_LIST = [
        'affiliation','constellation','sensor','acquisition_id','base_image_name','band_combo','year','month','day']
    if ACQS:
        TOOLTIP_FIELDS_LIST = [site_name_col] + TOOLTIP_FIELDS_LIST
        
    Map_Figure.add_child(m)
    
    # Add full-screen control to the map
    plugins.Fullscreen(
        position='topleft',
        title='Expand to fullscreen',
        title_cancel='Exit fullscreen',
        force_separate_button=True
    ).add_to(m)
    
    # Create combined field from affiliation, constellation/platform, and sensor
    gdf['combined_label'] = gdf['affiliation'].astype(str) + ' - ' + gdf['constellation'].astype(str)
    #+ ' - '\
    #+ gdf['sensor'].astype(str) + ' - ' 
    + gdf['image_type'].astype(str) 
    
    # Get unique combined values
    combined_values = gdf['combined_label'].unique()
    n_combinations = len(combined_values)
    # colors = ['red', 'blue', 'green', 'purple', 'orange', 'yellow', 'pink', 'brown', 'gray', 'cyan', 
    #           'darkred', 'lightred', 'darkblue', 'lightblue', 'darkgreen', 'lightgreen', 'cadetblue', make_CSDA_footprints_map
    #           'darkpurple', 'white', 'lightgray']
    # Create colors
    colors = plt.cm.plasma(np.linspace(0, 1, n_combinations))

    # Convert to hex colors for Folium
    colors = [mcolors.to_hex(color) for color in colors]
    
    # Create a feature group for each combined value
    for i, combined_val in enumerate(combined_values):
        color = colors[i % len(colors)]
        
        # Filter dataframe for just this combination
        combined_gdf = gdf[gdf['combined_label'] == combined_val]
        
        # Create a feature group for this combination
        fg = folium.FeatureGroup(name=f"{combined_val}")
        
        # Add the geometries to this feature group
        folium.GeoJson(
            combined_gdf,
            style_function=lambda x, color=color: {
                'fillColor': color,
                'color': 'black',
                'weight': 1,
                'opacity': 0.3,
                'fillOpacity': 0.15
            },
            tooltip=folium.GeoJsonTooltip(fields=TOOLTIP_FIELDS_LIST),
        ).add_to(fg)
        
        # Add the feature group to the map
        fg.add_to(m)
    
    # Convert numpy array to list for JSON serialization
    bounds = gdf.total_bounds.tolist()
    
    # Convert bounds to the format folium expects: [[south, west], [north, east]]
    folium_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
    
    # Now fit bounds
    m.fit_bounds(folium_bounds)
    
    # Add a legend
    legend_html = '''
    <div id='maplegend' class='maplegend' 
        style='position: absolute; z-index:9998; border:2px solid grey; background-color:rgba(255, 255, 255, 0.9);
         border-radius:6px; padding: 10px; font-size:12px; top: 5px; right: 150px;
         box-shadow: 0 0 15px rgba(0,0,0,0.2); max-height: 400px; overflow-y: auto; width: 250px;'>
         
    <div class='legend-title'><b>Affiliation - Constellation - Sensor</b></div>
    <div class='legend-scale'>
      <ul class='legend-labels'>
    '''
    
    # Add each combined value to the legend
    for i, combined_val in enumerate(combined_values):
        color = colors[i % len(colors)]
        # Truncate long labels if needed
        display_label = combined_val if len(combined_val) <= 35 else combined_val[:32] + "..."
        legend_html += f'<li><span style="background:{color};opacity:1;"></span>{display_label}</li>'
    
    legend_html += '''
      </ul>
    </div>
    </div>
    
    <style type='text/css'>
      .maplegend .legend-title {
        text-align: left;
        margin-bottom: 8px;
        font-weight: bold;
        font-size: 90%;
        color: #333;
        }
      .maplegend .legend-scale ul {
        margin: 0;
        margin-bottom: 5px;
        padding: 0;
        float: left;
        list-style: none;
        }
      .maplegend .legend-scale ul li {
        font-size: 80%;
        list-style: none;
        margin-left: 0;
        line-height: 18px;
        margin-bottom: 2px;
        color: #333;
        }
      .maplegend .legend-scale ul li span {
        display: block;
        float: left;
        height: 14px;
        width: 25px;
        margin-right: 6px;
        margin-left: 0;
        border: 1px solid #999;
        border-radius: 3px;
        }
      /* Ensure legend stays visible in fullscreen mode */
      .leaflet-fullscreen-on .maplegend {
        z-index: 99999 !important;
      }
    </style>
    '''

    # Change the legend positioning to top right
    legend_html = legend_html.replace('top: 5px; right: 150px;', 'top: 5px; right: 350px;')
        
    # Add the legend to the map
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Show map
    # #folium.TileLayer(basemaps['basemap_gray'].tiles, attr=' ', name="ESRI Basemap (gray)").add_to(m)
    # # Add custom basemaps
    # basemaps['Google Terrain'].add_to(m)
    # basemaps['Imagery'].add_to(m)
    # basemaps['ESRINatGeo'].add_to(m)
    # basemaps['basemap_gray'].add_to(m)

    # Add layer control to toggle on/off each layer
    m = MAP_CONTROL(m)
    
    return(m)
def MAP_CONTROL(m):
    LayerControl().add_to(m)
    plugins.Geocoder(position='bottomright').add_to(m)
    plugins.Fullscreen(position='bottomleft').add_to(m)
    plugins.MousePosition().add_to(m)
    return m
    
def dashed_style(feature):
    return {
        'color': 'black',       # Stroke color
        'weight': 2,            # Stroke width
        'opacity': 1.0,         # Stroke opacity (full)
        'fillOpacity': 0.1,     # Fill opacity
        'dashArray': '5, 5'     # Dashed line style (5px on, 5px off)
    }

# Extract platform
def extract_platform(platform_name):
        if pd.isna(platform_name):
            return 'Unknown'
        
        platform_str = str(platform_name)
        
        if platform_str.startswith('SPOT'):
            return 'SPOT'
        elif platform_str.startswith('WV'):
            return 'WorldView'
        elif platform_str.startswith('GE'):
            return 'GeoEye'
        elif platform_str.startswith('QB'):
            return 'QuickBird'
        elif 'PleiadesNeo' in platform_str:
            return 'PleiadesNeo'
        elif 'Pleiades' in platform_str or platform_str.startswith(('PHR')):
            return 'Pleiades'
        elif 'Legion' in platform_str or platform_str.startswith(('M3DS','P3DS')):
            return 'Legion'
        elif 'Sentinel' in platform_str:
            return 'Sentinel'
        elif 'Landsat' in platform_str:
            return 'Landsat'
        else:
            return platform_str
# Broken
# def link_acquisitions_to_sites(footprint_gdf, sites_gdf, buffer_distance=1000, 
#                                 site_name_col='Site Name'):
#     """
#     Link acquisitions to sites, handling cases where sites don't exactly overlap
#     with acquisition footprints but are nearby.
    
#     Parameters:
#     -----------
#     footprint_gdf : GeoDataFrame
#         Acquisition footprints (polygons)
#     sites_gdf : GeoDataFrame
#         Site locations (points)
#     buffer_distance : float, default=1000
#         Buffer distance around sites in CRS units (meters if using projected CRS)
#     site_name_col : str
#         Column name for site identifier
        
#     Returns:
#     --------
#     tuple: (footprint_with_sites, acquisition_site_mapping)
#         - footprint_with_sites: Original footprints with site info added (one row per acquisition)
#         - acquisition_site_mapping: DataFrame showing all site-acquisition relationships
#     """
#     import pandas as pd
#     import geopandas as gpd
    
#     # Ensure both are in same CRS (preferably projected for buffering)
#     if footprint_gdf.crs != sites_gdf.crs:
#         print(f"Reprojecting sites from {sites_gdf.crs} to {footprint_gdf.crs}")
#         sites_gdf = sites_gdf.to_crs(footprint_gdf.crs)
    
#     # Check if CRS is geographic (degrees) - warn about buffering
#     if sites_gdf.crs.is_geographic:
#         print(f"WARNING: CRS is geographic ({sites_gdf.crs}). Buffer distance will be in degrees.")
#         print(f"Consider reprojecting to a projected CRS for accurate buffering.")
    
#     # Buffer sites to capture nearby acquisitions
#     sites_buffered = sites_gdf.copy()
#     sites_buffered['geometry'] = sites_gdf.buffer(buffer_distance)
    
#     # Spatial join: find all acquisitions that intersect buffered sites
#     # This creates one row per acquisition-site pair
#     joined = gpd.sjoin(
#         footprint_gdf,
#         sites_buffered[[site_name_col, 'geometry']],
#         how='inner',  # Only keep acquisitions that intersect sites
#         predicate='intersects'
#     )
    
#     # Create mapping of acquisition_id to all associated sites
#     acquisition_site_mapping = joined.groupby('acquisition_id').agg({
#         site_name_col: lambda x: sorted(list(x.unique()))  # Sort alphabetically for consistency
#     }).reset_index()
#     acquisition_site_mapping.columns = ['acquisition_id', 'sites']
    
#     # Add count of sites per acquisition
#     acquisition_site_mapping['num_sites'] = acquisition_site_mapping['sites'].apply(len)
    
#     # Add primary site (first alphabetically)
#     acquisition_site_mapping['Primary_Site'] = acquisition_site_mapping['sites'].apply(
#         lambda x: x[0] if len(x) > 0 else None
#     )
    
#     # Merge back to original footprint_gdf to ensure we keep all acquisitions
#     footprint_with_sites = footprint_gdf.merge(
#         acquisition_site_mapping[['acquisition_id', 'Primary_Site', 'num_sites', 'sites']],
#         on='acquisition_id',
#         how='left'  # Keep all acquisitions, even those without sites
#     )
    
#     # Fill NaN for acquisitions not near any site
#     footprint_with_sites['Primary_Site'] = footprint_with_sites['Primary_Site'].fillna('Not CSDA Eval Site')
#     footprint_with_sites['num_sites'] = footprint_with_sites['num_sites'].fillna(0).astype(int)
#     footprint_with_sites['sites'] = footprint_with_sites['sites'].apply(
#         lambda x: x if isinstance(x, list) else []
#     )
    
#     # Verify no duplicates (should have one row per acquisition)
#     assert footprint_with_sites['acquisition_id'].duplicated().sum() == 0, \
#         "Error: Duplicate acquisition_ids found in result"
    
#     return footprint_with_sites, acquisition_site_mapping


# def create_comprehensive_summary(footprint_with_sites, acquisition_site_mapping, 
#                                    site_name_col='Primary_Site'):
#     """
#     Create comprehensive summaries accounting for multi-site acquisitions.
    
#     Parameters:
#     -----------
#     footprint_with_sites : GeoDataFrame
#         Footprints with site associations from link_acquisitions_to_sites()
#     acquisition_site_mapping : DataFrame
#         Acquisition-to-sites mapping from link_acquisitions_to_sites()
#     site_name_col : str
#         Column name for primary site
        
#     Returns:
#     --------
#     dict of DataFrames with various summaries
#     """
#     import pandas as pd
    
#     summaries = {}
    
#     # 1. Summary by site (primary site only - no double counting)
#     summary_by_site = footprint_with_sites.groupby(
#         [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
#     ).agg({
#         'acquisition_id': 'nunique',
#         'date': ['min', 'max']
#     }).reset_index()
    
#     summary_by_site.columns = [
#         site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type',
#         'acquisition_count', 'Earliest_Date', 'Latest_Date'
#     ]
#     summaries['by_site'] = summary_by_site.sort_values(
#         ['Latest_Date', site_name_col], 
#         ascending=[False, True]
#     ).reset_index(drop=True)
    
#     # 2. Summary by affiliation/constellation/sensor (total unique acquisitions)
#     summary_by_sensor = footprint_with_sites.groupby(
#         ['affiliation', 'constellation', 'sensor', 'image_type']
#     ).agg({
#         'acquisition_id': 'nunique',
#         'date': ['min', 'max']
#     }).reset_index()
    
#     summary_by_sensor.columns = [
#         'affiliation', 'constellation', 'sensor', 'image_type',
#         'total_acquisitions', 'Earliest_Date', 'Latest_Date'
#     ]
#     summaries['by_sensor'] = summary_by_sensor.sort_values(
#         'total_acquisitions', 
#         ascending=False
#     ).reset_index(drop=True)
    
#     # 3. Summary by affiliation only
#     summary_by_affiliation = footprint_with_sites.groupby('affiliation').agg({
#         'acquisition_id': 'nunique'
#     }).reset_index()
#     summary_by_affiliation.columns = ['affiliation', 'total_acquisitions']
#     summaries['by_affiliation'] = summary_by_affiliation.sort_values(
#         'total_acquisitions', 
#         ascending=False
#     ).reset_index(drop=True)
    
#     # 4. Summary by constellation
#     summary_by_constellation = footprint_with_sites.groupby(
#         ['affiliation', 'constellation']
#     ).agg({
#         'acquisition_id': 'nunique'
#     }).reset_index()
#     summary_by_constellation.columns = ['affiliation', 'constellation', 'total_acquisitions']
#     summaries['by_constellation'] = summary_by_constellation.sort_values(
#         'total_acquisitions', 
#         ascending=False
#     ).reset_index(drop=True)
    
#     # 5. Multi-site acquisitions analysis
#     multi_site_acqs = footprint_with_sites[footprint_with_sites['num_sites'] > 1]
#     if len(multi_site_acqs) > 0:
#         multi_site_summary = multi_site_acqs.groupby(
#             ['affiliation', 'constellation', 'sensor']
#         ).agg({
#             'acquisition_id': 'nunique',
#             'num_sites': 'mean'
#         }).reset_index()
#         multi_site_summary.columns = [
#             'affiliation', 'constellation', 'sensor',
#             'multi_site_acquisitions', 'avg_sites_per_acquisition'
#         ]
#         multi_site_summary['avg_sites_per_acquisition'] = multi_site_summary['avg_sites_per_acquisition'].round(2)
#         summaries['multi_site_acquisitions'] = multi_site_summary
#     else:
#         summaries['multi_site_acquisitions'] = pd.DataFrame()
    
#     # 6. Detailed site-by-site with ALL site associations
#     # This counts each acquisition for EVERY site it covers (allows double counting)
#     exploded_list = []
#     for _, row in acquisition_site_mapping.iterrows():
#         acq_id = row['acquisition_id']
#         sites = row['sites']
#         for site in sites:
#             exploded_list.append({'acquisition_id': acq_id, 'Site_Name': site})
    
#     if exploded_list:
#         exploded = pd.DataFrame(exploded_list)
        
#         # Merge with footprint data
#         detailed = exploded.merge(
#             footprint_with_sites[['acquisition_id', 'affiliation', 'constellation', 'sensor', 'image_type', 'date']],
#             on='acquisition_id',
#             how='left'
#         )
        
#         # Summary counting each acquisition for each site it covers
#         summary_all_sites = detailed.groupby(
#             ['Site_Name', 'affiliation', 'constellation', 'sensor', 'image_type']
#         ).agg({
#             'acquisition_id': 'nunique',
#             'date': ['min', 'max']
#         }).reset_index()
        
#         summary_all_sites.columns = [
#             'Site_Name', 'affiliation', 'constellation', 'sensor', 'image_type',
#             'acquisition_count', 'Earliest_Date', 'Latest_Date'
#         ]
#         summaries['by_site_all_associations'] = summary_all_sites.sort_values(
#             ['Latest_Date', 'Site_Name'], 
#             ascending=[False, True]
#         ).reset_index(drop=True)
        
#         # 7. Site coverage statistics
#         site_stats = detailed.groupby('Site_Name').agg({
#             'acquisition_id': 'nunique',
#             'affiliation': 'nunique',
#             'sensor': 'nunique'
#         }).reset_index()
#         site_stats.columns = ['Site_Name', 'total_acquisitions', 'num_affiliations', 'num_sensors']
#         summaries['site_statistics'] = site_stats.sort_values('total_acquisitions', ascending=False).reset_index(drop=True)
#     else:
#         summaries['by_site_all_associations'] = pd.DataFrame()
#         summaries['site_statistics'] = pd.DataFrame()
    
#     return summaries

# Orig  
def link_acquisitions_to_sites(footprint_gdf, sites_gdf, buffer_distance=1000, 
                                site_name_col_primary='Site Name Primary',
                                site_name_col='Site Name'):
    """
    Link acquisitions to sites, handling cases where sites don't exactly overlap
    with acquisition footprints but are nearby.
    
    Parameters:
    -----------
    footprint_gdf : GeoDataFrame
        Acquisition footprints (polygons)
    sites_gdf : GeoDataFrame
        Site locations (points)
    buffer_distance : float, default=1000
        Buffer distance around sites in CRS units (meters if using projected CRS)
    site_name_col_primary : str
        Column name for primary site identifier (if multiple sites associated with footprint, this is just the 'first'
        
    Returns:
    --------
    tuple: (footprint_with_sites, acquisition_site_mapping)
        - footprint_with_sites: Original footprints with site info added (one row per acquisition)
        - acquisition_site_mapping: DataFrame showing all site-acquisition relationships
    """
    import pandas as pd
    import geopandas as gpd
    
    # Ensure both are in same CRS (preferably projected for buffering)
    if footprint_gdf.crs != sites_gdf.crs:
        print(f"Reprojecting sites from {sites_gdf.crs} to {footprint_gdf.crs}")
        sites_gdf = sites_gdf.to_crs(footprint_gdf.crs)
    
    # Check if CRS is geographic (degrees) - warn about buffering
    if sites_gdf.crs.is_geographic:
        print(f"WARNING: CRS is geographic ({sites_gdf.crs}). Buffer distance will be in degrees.")
        print(f"Consider reprojecting to a projected CRS for accurate buffering.")
    
    # Buffer sites to capture nearby acquisitions
    sites_buffered = sites_gdf.copy()
    sites_buffered['geometry'] = sites_gdf.buffer(buffer_distance)
    
    # Spatial join: find all acquisitions that intersect buffered sites
    # This creates one row per acquisition-site pair
    joined = gpd.sjoin(
        footprint_gdf,
        sites_buffered[[site_name_col, 'geometry']],
        how='inner',  # Only keep acquisitions that intersect sites
        predicate='intersects'
    )
    
    # Create mapping of acquisition_id to all associated sites
    # Group by acquisition_id and aggregate the sites
    acquisition_site_mapping = joined.groupby('acquisition_id')[site_name_col].apply(
        lambda x: sorted(list(x.unique()))  # Sort alphabetically within each acquisition
    ).reset_index()
    acquisition_site_mapping.columns = ['acquisition_id', site_name_col]
    
    # Add count of sites per acquisition
    acquisition_site_mapping['num_sites'] = acquisition_site_mapping[site_name_col].apply(len)
    
    # Add primary site (first alphabetically for each acquisition)
    acquisition_site_mapping[site_name_col_primary] = acquisition_site_mapping[site_name_col].apply(
        lambda x: x[0] if len(x) > 0 else None
    )
    
    # Merge back to original footprint_gdf to ensure we keep all acquisitions
    footprint_with_sites = footprint_gdf.merge(
        acquisition_site_mapping[['acquisition_id', site_name_col, 'num_sites', site_name_col_primary]],
        on='acquisition_id',
        how='left'  # Keep all acquisitions, even those without sites
    )
    
    # Fill NaN for acquisitions not near any site
    footprint_with_sites[site_name_col_primary] = footprint_with_sites[site_name_col_primary].fillna('Not CSDA Eval Site')
    footprint_with_sites['num_sites'] = footprint_with_sites['num_sites'].fillna(0).astype(int)
    footprint_with_sites[site_name_col_primary] = footprint_with_sites[site_name_col_primary].apply(
        lambda x: x if isinstance(x, list) else []
    )
    
    # Verify no duplicates (should have one row per acquisition)
    duplicate_count = footprint_with_sites['acquisition_id'].duplicated().sum()
    if duplicate_count > 0:
        print(f"WARNING: Found {duplicate_count} duplicate acquisition_ids")
        # Show some examples
        duplicates = footprint_with_sites[footprint_with_sites['acquisition_id'].duplicated(keep=False)]
        print("Sample duplicates:")
        print(duplicates[['acquisition_id',site_name_col_primary, site_name_col]].head(10))
    
    return footprint_with_sites.to_crs(4326), acquisition_site_mapping

def create_comprehensive_summary(footprint_with_sites, acquisition_site_mapping, 
                                   site_name_col='site_primary',
                                   exclude_sites=None):
    """
    Create comprehensive summaries accounting for multi-site acquisitions.
    
    Parameters:
    -----------
    footprint_with_sites : GeoDataFrame
        Footprints with site associations from link_acquisitions_to_sites()
    acquisition_site_mapping : DataFrame
        Acquisition-to-sites mapping from link_acquisitions_to_sites()
    site_name_col : str
        Column name for primary site
    exclude_sites : list or str, optional
        Site name(s) to exclude from the summary. Can be a single string or list of strings.
        Default is None (no exclusions). Example: 'Not CSDA Eval Site' or ['Not CSDA Eval Site', 'Test Site']
        
    Returns:
    --------
    dict of DataFrames with various summaries
    """
    import pandas as pd
    
    # Handle exclude_sites parameter
    if exclude_sites is None:
        exclude_sites = []
    elif isinstance(exclude_sites, str):
        exclude_sites = [exclude_sites]
    
    # Filter out excluded sites
    if exclude_sites:
        footprint_with_sites = footprint_with_sites[~footprint_with_sites[site_name_col].isin(exclude_sites)].copy()
        acquisition_site_mapping = acquisition_site_mapping.copy()
        # Filter sites from the site list column
        acquisition_site_mapping[site_name_col] = acquisition_site_mapping[site_name_col].apply(
            lambda sites: [s for s in sites if s not in exclude_sites]
        )
        # Remove acquisitions that no longer have any sites
        acquisition_site_mapping = acquisition_site_mapping[
            acquisition_site_mapping[site_name_col].apply(len) > 0
        ]
    
    summaries = {}
    
    # 1. Summary by site (primary site only - no double counting)
    summary_by_site = footprint_with_sites.groupby(
        [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
    ).agg({
        'acquisition_id': 'nunique',
        'date': ['min', 'max']
    }).reset_index()
    
    summary_by_site.columns = [
        site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type',
        'acquisition_count', 'Earliest_Date', 'Latest_Date'
    ]
    summaries['by_site'] = summary_by_site.sort_values(
        ['Latest_Date', site_name_col], 
        ascending=[False, True]
    ).reset_index(drop=True)
    
    # 2. Summary by affiliation/constellation/sensor (total unique acquisitions)
    summary_by_sensor = footprint_with_sites.groupby(
        ['affiliation', 'constellation', 'sensor', 'image_type']
    ).agg({
        'acquisition_id': 'nunique',
        'date': ['min', 'max']
    }).reset_index()
    
    summary_by_sensor.columns = [
        'affiliation', 'constellation', 'sensor', 'image_type',
        'total_acquisitions', 'Earliest_Date', 'Latest_Date'
    ]
    summaries['by_sensor'] = summary_by_sensor.sort_values(
        'total_acquisitions', 
        ascending=False
    ).reset_index(drop=True)
    
    # 3. Summary by affiliation only
    summary_by_affiliation = footprint_with_sites.groupby('affiliation').agg({
        'acquisition_id': 'nunique'
    }).reset_index()
    summary_by_affiliation.columns = ['affiliation', 'total_acquisitions']
    summaries['by_affiliation'] = summary_by_affiliation.sort_values(
        'total_acquisitions', 
        ascending=False
    ).reset_index(drop=True)
    
    # 4. Summary by constellation
    summary_by_constellation = footprint_with_sites.groupby(
        ['affiliation', 'constellation']
    ).agg({
        'acquisition_id': 'nunique'
    }).reset_index()
    summary_by_constellation.columns = ['affiliation', 'constellation', 'total_acquisitions']
    summaries['by_constellation'] = summary_by_constellation.sort_values(
        'total_acquisitions', 
        ascending=False
    ).reset_index(drop=True)
    
    # 5. Multi-site acquisitions analysis
    multi_site_acqs = footprint_with_sites[footprint_with_sites['num_sites'] > 1]
    if len(multi_site_acqs) > 0:
        multi_site_summary = multi_site_acqs.groupby(
            ['affiliation', 'constellation', 'sensor']
        ).agg({
            'acquisition_id': 'nunique',
            'num_sites': 'mean'
        }).reset_index()
        multi_site_summary.columns = [
            'affiliation', 'constellation', 'sensor',
            'multi_site_acquisitions', 'avg_sites_per_acquisition'
        ]
        multi_site_summary['avg_sites_per_acquisition'] = multi_site_summary['avg_sites_per_acquisition'].round(2)
        summaries['multi_site_acquisitions'] = multi_site_summary
    else:
        summaries['multi_site_acquisitions'] = pd.DataFrame()
    
    # 6. Detailed site-by-site with ALL site associations
    # This counts each acquisition for EVERY site it covers (allows double counting)
    exploded_list = []
    for _, row in acquisition_site_mapping.iterrows():
        acq_id = row['acquisition_id']
        sites = row[site_name_col]
        for site in sites:
            exploded_list.append({'acquisition_id': acq_id, 'Site_Name': site})
    
    if exploded_list:
        exploded = pd.DataFrame(exploded_list)
        
        # Merge with footprint data
        detailed = exploded.merge(
            footprint_with_sites[['acquisition_id', 'affiliation', 'constellation', 'sensor', 'image_type', 'date']],
            on='acquisition_id',
            how='left'
        )
        
        # Summary counting each acquisition for each site it covers
        summary_all_sites = detailed.groupby(
            ['Site_Name', 'affiliation', 'constellation', 'sensor', 'image_type']
        ).agg({
            'acquisition_id': 'nunique',
            'date': ['min', 'max']
        }).reset_index()
        
        summary_all_sites.columns = [
            'Site_Name', 'affiliation', 'constellation', 'sensor', 'image_type',
            'acquisition_count', 'Earliest_Date', 'Latest_Date'
        ]
        summaries['by_site_all_associations'] = summary_all_sites.sort_values(
            ['Latest_Date', 'Site_Name'], 
            ascending=[False, True]
        ).reset_index(drop=True)
        
        # 7. Site coverage statistics
        site_stats = detailed.groupby('Site_Name').agg({
            'acquisition_id': 'nunique',
            'affiliation': 'nunique',
            'sensor': 'nunique'
        }).reset_index()
        site_stats.columns = ['Site_Name', 'total_acquisitions', 'num_affiliations', 'num_sensors']
        summaries['site_statistics'] = site_stats.sort_values('total_acquisitions', ascending=False).reset_index(drop=True)
    else:
        summaries['by_site_all_associations'] = pd.DataFrame()
        summaries['site_statistics'] = pd.DataFrame()
    
    # Calculate summary statistics from the original footprint_with_sites DataFrame
    n_affiliations = footprint_with_sites['affiliation'].nunique()
    n_constellations = footprint_with_sites['constellation'].nunique()
    n_sites = footprint_with_sites[site_name_col].nunique()
    n_images = footprint_with_sites['acquisition_id'].nunique()
    
    # Print summary statistics
    print("\n" + "="*70)
    print("Summary of acquisitions at CSDA Evaluation Sites")
    if exclude_sites:
        print(f"(excluding sites: {', '.join(exclude_sites)})")
    print("="*70)
    print(f"Total Affiliations:        {n_affiliations:>6}")
    print(f"Total Constellations:      {n_constellations:>6}")
    print(f"Total Evaluation Sites:    {n_sites:>6}")
    print(f"Total Images:              {n_images:>6}")
    print("-"*70)
    
    # Print breakdown by affiliation
    print("\nBreakdown by Affiliation:")
    for _, row in summaries['by_affiliation'].iterrows():
        affiliation = row['affiliation']
        count = row['total_acquisitions']
        print(f"  {affiliation:<20} {count:>6} images")
    
    # Print breakdown by constellation
    print("\nBreakdown by Constellation:")
    for _, row in summaries['by_constellation'].iterrows():
        affiliation = row['affiliation']
        constellation = row['constellation']
        count = row['total_acquisitions']
        print(f"  {affiliation}/{constellation:<30} {count:>6} images")
    
    print("="*70 + "\n")
    
    return summaries
    
# def create_site_summary(footprint_gdf, sites_gdf, site_name_col='Site Name', 
#                         format='detailed', include_non_site_images=True):
#     """
#     Create a summary of images by site, with options for detailed or pivot format.
    
#     Parameters:
#     -----------
#     footprint_gdf : GeoDataFrame
#         Footprint geodataframe with image metadata
#     sites_gdf : GeoDataFrame
#         Sites geodataframe
#     site_name_col : str
#         Column name in sites_gdf that identifies each site
#     format : str, default='detailed'
#         Output format: 'detailed' (long format) or 'pivot' (wide format)
#     include_non_site_images : bool, default=True
#         If True, includes images not associated with any site as 'Not CSDA Site'
    
#     Returns:
#     --------
#     pd.DataFrame
#         Summary table in requested format
#     """
#     import pandas as pd
#     import geopandas as gpd
    
#     # Ensure both GDFs are in the same CRS
#     if footprint_gdf.crs != sites_gdf.crs:
#         print(f"Reprojecting footprints from {footprint_gdf.crs} to {sites_gdf.crs}")
#         footprint_gdf = footprint_gdf.to_crs(sites_gdf.crs)
    
#     # Perform spatial intersection
#     join_type = 'left' if include_non_site_images else 'inner'
#     intersected = gpd.sjoin(
#         footprint_gdf, 
#         sites_gdf, 
#         how=join_type, 
#         predicate='intersects'
#     )
    
#     # Fill in 'Not CSDA Site' for footprints that don't intersect with any site
#     NOT_CSDA_STR = 'Not CSDA Eval Site'
#     if include_non_site_images:
#         if site_name_col in intersected.columns:
#             intersected[site_name_col] = intersected[site_name_col].fillna(NOT_CSDA_STR)
#         else:
#             intersected[site_name_col] = NOT_CSDA_STR
    
#     # Check if required columns exist
#     if site_name_col not in intersected.columns:
#         raise ValueError(f"Column '{site_name_col}' not found in sites_gdf")
    
#     if 'sensor' not in intersected.columns:
#         raise ValueError("Column 'sensor' not found in footprint_gdf. Run get_attributes_from_filename first.")
    
#     # Generate summary based on format
#     if format.lower() == 'pivot':
#         # Create combined affiliation-constellation label
#         intersected['affiliation_constellation'] = (
#             intersected['affiliation'].astype(str) + ' - ' + 
#             intersected['constellation'].astype(str)
#         )
        
#         # Group and count
#         summary = intersected.groupby(
#             [site_name_col, 'affiliation_constellation']
#         ).size().reset_index(name='count')
        
#         # Create pivot table
#         pivot = summary.pivot(
#             index=site_name_col,
#             columns='affiliation_constellation',
#             values='count'
#         ).fillna(0).astype(int)
        
#         # Sort columns alphabetically
#         pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        
#         # Add total column
#         pivot['Total'] = pivot.sum(axis=1)
        
#         # Sort by total descending
#         pivot = pivot.sort_values('Total', ascending=False)
        
#         return pivot
    
#     else:  # detailed format (default)
#         # Group by site, affiliation, constellation, sensor, and image_type
#         summary = intersected.groupby(
#             [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
#         ).size().reset_index(name='acquisition_count')
        
#         # Add date range if available
#         if 'date' in intersected.columns:
#             date_range = intersected.groupby(
#                 [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
#             )['date'].agg(['min', 'max']).reset_index()
            
#             summary = summary.merge(
#                 date_range,
#                 on=[site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type'],
#                 how='left'
#             )
#             summary.rename(columns={'min': 'Earliest_Date', 'max': 'Latest_Date'}, inplace=True)
        
#         # Sort by Latest_Date descending (most recent first), then by site name
#         if 'Latest_Date' in summary.columns:
#             summary = summary.sort_values(['Latest_Date', site_name_col], ascending=[False, True])
#         else:
#             summary = summary.sort_values([site_name_col, 'acquisition_count'], ascending=[True, False])
        
#         summary = summary.reset_index(drop=True)
        
#         return summary
def create_site_summary(footprint_gdf, sites_gdf=None, site_name_col='Site Name', 
                        format='detailed', include_non_site_images=True):
    """
    Create a summary of images by site, with options for detailed or pivot format.
    
    Parameters:
    -----------
    footprint_gdf : GeoDataFrame
        Footprint geodataframe with image metadata (must have 'Site Name' column if sites_gdf is None)
    sites_gdf : GeoDataFrame, optional
        Sites geodataframe. If None, assumes footprint_gdf already has site information
    site_name_col : str
        Column name that identifies each site
    format : str, default='detailed'
        Output format: 'detailed' (long format) or 'pivot' (wide format)
    include_non_site_images : bool, default=True
        If True, includes images not associated with any site as 'Not CSDA Site'
    
    Returns:
    --------
    pd.DataFrame
        Summary table in requested format
    """
    import pandas as pd
    import geopandas as gpd
    
    NOT_CSDA_STR = 'Not CSDA Eval Site'
    
    # If sites_gdf is provided, do spatial join
    if sites_gdf is not None:
        # Ensure both GDFs are in the same CRS
        if footprint_gdf.crs != sites_gdf.crs:
            print(f"Reprojecting footprints from {footprint_gdf.crs} to {sites_gdf.crs}")
            footprint_gdf = footprint_gdf.to_crs(sites_gdf.crs)
        
        join_type = 'left' if include_non_site_images else 'inner'
        intersected = gpd.sjoin(
            footprint_gdf, 
            sites_gdf, 
            how=join_type, 
            predicate='intersects'
        )
        
        # Fill in 'Not CSDA Site' for footprints that don't intersect
        if include_non_site_images:
            if site_name_col in intersected.columns:
                intersected[site_name_col] = intersected[site_name_col].fillna(NOT_CSDA_STR)
    else:
        # Use footprint_gdf as-is (already has site info)
        intersected = footprint_gdf.copy()
        
        # Fill in 'Not CSDA Site' for footprints without a site
        if include_non_site_images and site_name_col in intersected.columns:
            intersected[site_name_col] = intersected[site_name_col].fillna(NOT_CSDA_STR)
    
    # Check if required columns exist
    if site_name_col not in intersected.columns:
        raise ValueError(f"Column '{site_name_col}' not found. Either provide sites_gdf or ensure footprint_gdf has '{site_name_col}' column.")
    
    if 'sensor' not in intersected.columns:
        raise ValueError("Column 'sensor' not found in footprint_gdf.")
    
    # Generate summary based on format
    if format.lower() == 'pivot':
        # Create combined affiliation-constellation label
        intersected['affiliation_constellation'] = (
            intersected['affiliation'].astype(str) + ' - ' + 
            intersected['constellation'].astype(str)
        )
        
        # Group and count unique acquisitions
        if 'acquisition_id' in intersected.columns:
            summary = intersected.groupby(
                [site_name_col, 'affiliation_constellation']
            )['acquisition_id'].nunique().reset_index(name='count')
        else:
            summary = intersected.groupby(
                [site_name_col, 'affiliation_constellation']
            ).size().reset_index(name='count')
        
        # Create pivot table
        pivot = summary.pivot(
            index=site_name_col,
            columns='affiliation_constellation',
            values='count'
        ).fillna(0).astype(int)
        
        # Sort columns alphabetically
        pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        
        # Add total column
        pivot['Total'] = pivot.sum(axis=1)
        
        # Sort by total descending
        pivot = pivot.sort_values('Total', ascending=False)
        
        return pivot
    
    else:  # detailed format (default)
        # Group by site, affiliation, constellation, sensor, and image_type
        # Use acquisition_id to count unique acquisitions
        if 'acquisition_id' in intersected.columns:
            summary = intersected.groupby(
                [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
            )['acquisition_id'].nunique().reset_index(name='acquisition_count')
        else:
            summary = intersected.groupby(
                [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
            ).size().reset_index(name='acquisition_count')
        
        # Add date range if available
        if 'date' in intersected.columns:
            date_range = intersected.groupby(
                [site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type']
            )['date'].agg(['min', 'max']).reset_index()
            
            summary = summary.merge(
                date_range,
                on=[site_name_col, 'affiliation', 'constellation', 'sensor', 'image_type'],
                how='left'
            )
            summary.rename(columns={'min': 'Earliest_Date', 'max': 'Latest_Date'}, inplace=True)
        
        # Sort by Latest_Date descending (most recent first), then by site name
        if 'Latest_Date' in summary.columns:
            summary = summary.sort_values(['Latest_Date', site_name_col], ascending=[False, True])
        else:
            summary = summary.sort_values([site_name_col, 'acquisition_count'], ascending=[True, False])
        
        summary = summary.reset_index(drop=True)
        
        return summary
    
def display_summary_as_markdown(summary_df, title=None, include_index=False):
    """
    Convert summary DataFrame to formatted markdown table.
    
    Parameters:
    -----------
    summary_df : pd.DataFrame
        Summary dataframe to convert
    title : str, optional
        Title to display above the table
    include_index : bool, default=False
        Whether to include the dataframe index in output
    
    Returns:
    --------
    str
        Markdown formatted table
    """
    import pandas as pd
    from io import StringIO
    
    # Create markdown string
    markdown_lines = []
    
    # Add title if provided
    if title:
        markdown_lines.append(f"## {title}\n")
    
    # Convert to markdown
    md_table = summary_df.to_markdown(index=include_index)
    markdown_lines.append(md_table)
    
    # Add summary statistics
    if 'acquisition_count' in summary_df.columns:
        total_images = summary_df['acquisition_count'].sum()
        markdown_lines.append(f"\n**Total Images:** {total_images:,}")
    
    if 'Site' in summary_df.columns:
        num_sites = summary_df['Site'].nunique()
        markdown_lines.append(f"  \n**Number of Sites:** {num_sites}")
    
    if 'Constellation' in summary_df.columns:
        num_platforms = summary_df['Constellation'].nunique()
        markdown_lines.append(f"  \n**Number of Constellations/Platforms:** {num_platforms}")
    
    return '\n'.join(markdown_lines)


def print_summary_markdown(summary_df, title=None):
    """
    Print summary as formatted markdown (for Jupyter notebooks).
    
    Parameters:
    -----------
    summary_df : pd.DataFrame
        Summary dataframe to display
    title : str, optional
        Title to display above the table
    """
    from IPython.display import display, Markdown
    
    md_text = display_summary_as_markdown(summary_df, title)
    display(Markdown(md_text))


def save_summaries_to_markdown(footprint_gdf, sites_gdf, output_file='image_summary.md', 
                               site_name_col='site_name'):
    """
    Generate all summary tables and save to a markdown file.
    
    Parameters:
    -----------
    footprint_gdf : GeoDataFrame
        Footprint geodataframe with image metadata
    sites_gdf : GeoDataFrame
        Sites geodataframe
    output_file : str, default='image_summary.md'
        Output markdown file path
    site_name_col : str, default='site_name'
        Column name in sites_gdf that identifies each site
    """
    import pandas as pd
    from datetime import datetime
    
    # Generate summaries
    basic_summary = summarize_images_by_site(footprint_gdf, sites_gdf, site_name_col)
    detailed_summary = summarize_images_by_site_detailed(footprint_gdf, sites_gdf, site_name_col)
    pivot_summary = create_site_summary_pivot(footprint_gdf, sites_gdf, site_name_col)
    
    # Create markdown document
    md_lines = []
    
    # Header
    md_lines.append("# Satellite Image Summary by Site")
    md_lines.append(f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    md_lines.append("---\n")
    
    # Basic Summary
    md_lines.append("## Summary by Site, Affiliation, and Constellation (Platform)\n")
    md_lines.append(basic_summary.to_markdown(index=False))
    
    total_images = basic_summary['acquisition_count'].sum()
    num_sites = basic_summary['Site'].nunique()
    num_Affiliation = basic_summary['Affiliation'].nunique()
    
    md_lines.append(f"\n**Statistics:**")
    md_lines.append(f"- Total Images: {total_images:,}")
    md_lines.append(f"- Number of Sites: {num_sites}")
    md_lines.append(f"- Number of Affiliations: {num_Affiliation}")
    md_lines.append("\n---\n")
    
    # Detailed Summary (if dates available)
    if 'Earliest_Date' in detailed_summary.columns:
        md_lines.append("## Detailed Summary with Date Ranges\n")
        md_lines.append(detailed_summary.to_markdown(index=False))
        md_lines.append("\n---\n")
    
    # Pivot Table
    md_lines.append("## Image Count by Site and Constellation (Platform) (Pivot Table)\n")
    md_lines.append(pivot_summary.to_markdown(index=True))
    md_lines.append("\n---\n")
    
    # Site-by-Site Breakdown
    md_lines.append("## Site-by-Site Breakdown\n")
    for site in basic_summary['Site'].unique():
        site_data = basic_summary[basic_summary['Site'] == site]
        site_total = site_data['acquisition_count'].sum()
        
        md_lines.append(f"### {site}")
        md_lines.append(f"\n**Total Images: {site_total:,}**\n")
        md_lines.append(site_data[['Affiliation', 'Constellation', 'acquisition_count']].to_markdown(index=False))
        md_lines.append("\n")
    
    # Write to file
    with open(output_file, 'w') as f:
        f.write('\n'.join(md_lines))
    
    print(f"Markdown summary saved to: {output_file}")
    
    return '\n'.join(md_lines)


def create_styled_summary_html(summary_df, title="Image Summary"):
    """
    Create a styled HTML table for better visualization.
    
    Parameters:
    -----------
    summary_df : pd.DataFrame
        Summary dataframe to display
    title : str, default="Image Summary"
        Title for the table
    
    Returns:
    --------
    str
        HTML formatted table with styling
    """
    html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #2c3e50;">{title}</h2>
        {summary_df.to_html(index=False, classes='summary-table', border=0)}
    </div>
    
    <style>
        .summary-table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 20px;
        }}
        .summary-table th {{
            background-color: #3498db;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }}
        .summary-table td {{
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }}
        .summary-table tr:hover {{
            background-color: #f5f5f5;
        }}
        .summary-table tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
    </style>
    """
    return html


def display_summary_html(summary_df, title="Image Summary"):
    """
    Display summary as styled HTML in Jupyter notebook.
    
    Parameters:
    -----------
    summary_df : pd.DataFrame
        Summary dataframe to display
    title : str, default="Image Summary"
        Title for the table
    """
    from IPython.display import display, HTML
    
    html = create_styled_summary_html(summary_df, title)
    display(HTML(html))

import glob
import os
import re
from datetime import datetime
from collections import defaultdict

def find_and_rename_all_latest_files(directory, extensions=['csv', 'gpkg'], pattern='*202?-??-??'):
    """
    Find the latest dated file for EACH unique basename and rename to *_latest.{ext}
    Works with multiple file extensions (csv, gpkg, etc.)
    
    For example:
        footprints_2026-01-15.csv -> footprints_latest.csv
        footprints_2026-01-16.gpkg -> footprints_latest.gpkg
        sites_2026-01-16.csv -> sites_latest.csv
    
    Parameters:
    -----------
    directory : str
        Directory to search in
    extensions : list of str
        File extensions to process (e.g., ['csv', 'gpkg'])
    pattern : str
        Date pattern to match (default: '*202?-??-??')
    
    Returns:
    --------
    dict: Mapping of basename_ext to latest file path
    """
    
    # Ensure extensions is a list
    if isinstance(extensions, str):
        extensions = [extensions]
    
    # Find all matching files for all extensions
    all_files = []
    for ext in extensions:
        search_pattern = os.path.join(directory, f"{pattern}.{ext}")
        files = glob.glob(search_pattern)
        all_files.extend(files)
    
    if not all_files:
        print(f"No files found matching pattern: {pattern} with extensions: {extensions}")
        return {}
    
    print(f"Found {len(all_files)} dated files")
    
    # Group files by basename AND extension
    basename_ext_files = defaultdict(list)
    date_pattern = r'(.+?)_?(\d{4}-\d{2}-\d{2})\.([a-zA-Z0-9]+)$'
    
    for filepath in all_files:
        filename = os.path.basename(filepath)
        match = re.search(date_pattern, filename)
        
        if match:
            basename = match.group(1)
            date_str = match.group(2)
            ext = match.group(3)
            
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                key = f"{basename}.{ext}"  # Group by basename AND extension
                basename_ext_files[key].append((filepath, date_obj, date_str, basename, ext))
            except ValueError:
                print(f"Warning: Could not parse date from {filename}")
                continue
    
    if not basename_ext_files:
        print("No files with valid dates found")
        return {}
    
    # Process each basename-extension group
    latest_files = {}
    
    print("\n=== Processing files ===")
    for key, file_list in sorted(basename_ext_files.items()):
        # Sort by date and get the most recent
        file_list.sort(key=lambda x: x[1], reverse=True)
        latest_file, latest_date, date_str, basename, ext = file_list[0]
        
        # Create new filename
        new_name = f"{basename}_latest.{ext}"
        new_path = os.path.join(directory, new_name)
        
        # Remove existing *_latest.{ext} for this basename if it exists
        if os.path.exists(new_path) and new_path != latest_file:
            print(f"  Removing old: {new_name}")
            os.remove(new_path)
        
        # Rename the file
        if latest_file != new_path:  # Don't rename if already named correctly
            os.rename(latest_file, new_path)
            print(f"  Renamed: {os.path.basename(latest_file)} -> {new_name} (date: {date_str})")
        else:
            print(f"  Already latest: {new_name} (date: {date_str})")
        
        latest_files[key] = new_path
    
    return latest_files


def copy_all_latest_files(directory, extensions=['csv', 'gpkg'], pattern='*20??-??-??'):
    """
    Copy the latest dated file for EACH unique basename to *_latest.{ext} (keeps originals)
    Works with multiple file extensions.
    """
    import shutil
    
    # Ensure extensions is a list
    if isinstance(extensions, str):
        extensions = [extensions]
    
    # Find all matching files for all extensions
    all_files = []
    for ext in extensions:
        search_pattern = os.path.join(directory, f"{pattern}.{ext}")
        files = glob.glob(search_pattern)
        all_files.extend(files)
    
    if not all_files:
        print(f"No files found matching pattern: {pattern} with extensions: {extensions}")
        return {}
    
    print(f"Found {len(all_files)} dated files")
    
    # Group files by basename AND extension
    basename_ext_files = defaultdict(list)
    date_pattern = r'(.+?)_?(\d{4}-\d{2}-\d{2})\.([a-zA-Z0-9]+)$'
    
    for filepath in all_files:
        filename = os.path.basename(filepath)
        match = re.search(date_pattern, filename)
        
        if match:
            basename = match.group(1)
            date_str = match.group(2)
            ext = match.group(3)
            
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                key = f"{basename}.{ext}"
                basename_ext_files[key].append((filepath, date_obj, date_str, basename, ext))
            except ValueError:
                continue
    
    if not basename_ext_files:
        return {}
    
    # Process each basename-extension group
    latest_files = {}
    
    print("\n=== Processing files ===")
    for key, file_list in sorted(basename_ext_files.items()):
        # Sort by date and get the most recent
        file_list.sort(key=lambda x: x[1], reverse=True)
        latest_file, latest_date, date_str, basename, ext = file_list[0]
        
        # Create new filename
        new_name = f"{basename}_latest.{ext}"
        new_path = os.path.join(directory, new_name)
        
        # Remove existing *_latest.{ext} if it exists
        if os.path.exists(new_path):
            print(f"  Removing old: {new_name}")
            os.remove(new_path)
        
        # Copy the file
        shutil.copy2(latest_file, new_path)
        print(f"  Copied: {os.path.basename(latest_file)} -> {new_name} (date: {date_str})")
        
        latest_files[key] = new_path
    
    return latest_files

def buffer_site_gdf(gdf, BUF_KM):
    """
    Buffer a GeoDataFrame by BUF_KM km.
    For global datasets, buffers each site in its own appropriate UTM zone.
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        Input GeoDataFrame to buffer
    BUF_KM : float
        Buffer distance in kilometers
        
    Returns:
    --------
    GeoDataFrame with buffered geometries in original CRS
    """
    # Check if CRS is geographic (lat/lon), if so reproject to metric
    if gdf.crs and gdf.crs.is_geographic:
        original_crs = gdf.crs
        
        # Create empty list to store buffered geometries (in original CRS)
        buffered_geoms = []
        
        # Buffer each site individually in its own UTM zone
        for idx, row in gdf.iterrows():
            # Skip if geometry is None or empty
            if row.geometry is None or row.geometry.is_empty:
                print(f"Warning: Skipping empty geometry at index {idx}")
                buffered_geoms.append(row.geometry)  # Keep the empty geometry
                continue
            
            # Create single-row GeoDataFrame for this site
            site_gdf = gpd.GeoDataFrame([row], geometry='geometry', crs=original_crs)
            
            # Get approximate center using bounds (avoids centroid warning)
            try:
                bounds = row.geometry.bounds  # (minx, miny, maxx, maxy)
                lon = (bounds[0] + bounds[2]) / 2
                lat = (bounds[1] + bounds[3]) / 2
            except Exception as e:
                print(f"Warning: Could not get bounds for index {idx}: {e}")
                buffered_geoms.append(row.geometry)
                continue
            
            # For equatorial regions (within 5 degrees of equator), use Azimuthal Equidistant
            if abs(lat) < 5:
                proj_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
            else:
                # Use UTM zone appropriate for this specific site
                try:
                    proj_crs = site_gdf.estimate_utm_crs()
                except Exception as e:
                    print(f"Warning: Could not estimate UTM CRS for index {idx}: {e}")
                    # Fallback to Azimuthal Equidistant
                    proj_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
            
            # Project, buffer, and reproject back to original CRS
            try:
                site_projected = site_gdf.to_crs(proj_crs)
                site_buffered_projected = site_projected.buffer(BUF_KM * 1000).iloc[0]
                
                # Convert buffered geometry back to original CRS
                site_buffered_gdf = gpd.GeoDataFrame([{'geometry': site_buffered_projected}], 
                                                       geometry='geometry', 
                                                       crs=proj_crs)
                site_buffered_original = site_buffered_gdf.to_crs(original_crs).geometry.iloc[0]
                
                # Store the buffered geometry (now in original CRS)
                buffered_geoms.append(site_buffered_original)
            except Exception as e:
                print(f"Warning: Could not buffer geometry at index {idx}: {e}")
                buffered_geoms.append(row.geometry)  # Keep original geometry
                continue
        
        # Create new GeoDataFrame with buffered geometries
        gdf_buffered = gdf.copy()
        gdf_buffered['geometry'] = buffered_geoms
        
        return gdf_buffered
    else:
        # Already in projected CRS (assumed to be in meters)
        gdf_buffered = gdf.copy()
        gdf_buffered['geometry'] = gdf.buffer(BUF_KM * 1000)  
        return gdf_buffered

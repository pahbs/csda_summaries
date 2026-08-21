# csdalib_refactored.py
import re, json, glob, os
from pathlib import Path
import xml.etree.ElementTree as ET
import geopandas as gpd
from shapely.geometry import shape

import pandas as pd

import os, sys
sys.path.append('/home/pmontesa/code/csda_summaries/lib')
from sensor_profiles import SENSOR_PROFILES

sys.path.append('/home/pmontesa/code/geoscitools')
import footprintlib

import numpy as np
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import contextily as ctx

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

def _get_nested(d, dotted_path):
    """Walk dotted path through nested dict, return None if missing."""
    cur = d
    #print(f'Dotted path: {dotted_path}')
    for key in dotted_path.split('.'):
        #print(f'key: {key}')
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur

def detect_vendor(file_path, profiles=SENSOR_PROFILES):
    """Match a file path against vendor detection patterns. Returns profile key."""
    fn = Path(file_path).name
    for key, prof in profiles.items():
        for pat in prof['detect'].get('filename_patterns', []):
            if re.search(pat, fn, re.IGNORECASE):
                return key
    return None

def find_metadata_file(file_path, profile):
    fp = Path(file_path)
    finder = profile['metadata_finder']

    # Self-referencing metadata (e.g., Pixxel _FPT.geojson)
    if finder['type'] == 'self':
        return fp

    # Compute base variants
    base          = fp.stem
    base_clean    = re.sub(r'_(CLOUD|L1[ABC]|L2A)_\d+$', '', base, flags=re.I)
    base_no_tile  = re.sub(finder.get('tile_pattern', r'_R\d+C\d+'), '', base)
    
    # NEW: 'base_dim' — for Airbus IMG_*.TIF → DIM_*.XML pairing
    base_dim = base.replace('IMG_', '', 1)               # remove IMG_ prefix
    base_dim = re.sub(r'_R\d+C\d+', '', base_dim)        # strip tile suffix
    base_dim = re.sub(r'_RGB$|_NED$|_RGBN$|_BGRN$|_P$', '', base_dim)  # strip band-combo
    base_dim = re.sub(r'-\d+$', '', base_dim)            # strip trailing -N (e.g., -1)

    # Try exact pattern
    candidates = [
        finder['pattern'].format(
            base=base,
            base_clean=base_clean,
            base_no_tile=base_no_tile,
            base_dim=base_dim,
        )
    ]
    for c in candidates:
        p = fp.parent / c
        if p.exists():
            return p

    # Fallback: glob the directory
    if 'fallback_glob' in finder:
        for g in fp.parent.glob(finder['fallback_glob']):
            return g

    return None


def parse_metadata(metadata_path, profile):
    """Read metadata file (JSON or XML) and extract fields per profile."""
    if metadata_path is None or not Path(metadata_path).exists():
        return {}

    fmt = profile.get('metadata_format', 'xml')
    extracted = {}

    if fmt == 'json':
        with open(metadata_path) as f:
            doc = json.load(f)
        for std_key, json_path in profile['fields'].items():
            extracted[std_key] = _get_nested(doc, json_path)
        # Geometry from inline GeoJSON
        if profile['geometry_source']['type'] == 'inline_geojson':
            geom_data = _get_nested(doc, profile['geometry_source']['path'])
            extracted['_inline_geometry'] = shape(geom_data) if geom_data else None
            extracted['_inline_crs'] = profile['geometry_source'].get('crs', 'EPSG:4326')

    elif fmt == 'xml':
        tree = ET.parse(metadata_path)
        root = tree.getroot()
        
        # Strip XML namespaces (DIMAP files often have them)
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]
        
        for std_key, spec in profile['fields'].items():
            if isinstance(spec, str):
                tags = [spec]
            else:
                tags = [spec['tag']] + spec.get('fallback_tags', [])
            
            value = None
            for tag in tags:
                elem = root.find(f'.//{tag}')
                if elem is not None and elem.text:
                    value = elem.text.strip()
                    if isinstance(spec, dict) and spec.get('cast') == 'int':
                        try: value = int(value)
                        except: pass
                    break
            extracted[std_key] = value

    return extracted

def extract_from_filename(file_path, profile):
    """Pull additional fields directly from the filename."""
    fn = Path(file_path).name
    extracted = {}
    for std_key, pattern in profile.get('extract_from_filename', {}).items():
        m = re.search(pattern, fn, re.IGNORECASE)
        if m:
            extracted[std_key] = m.group(1)
    return extracted

def resolve_sensor_name(extracted, profile):
    """Apply sensor_lookup or regex rules."""
    raw = (extracted.get('sensor_id_raw')
           or extracted.get('mission')
           or '')
    raw = str(raw)

    # NEW: combine MISSION + MISSION_INDEX (Airbus DIMAP)
    if 'sensor_combine_mission_and_index' in profile:
        mission = str(extracted.get('mission') or '').strip().upper()
        idx     = str(extracted.get('mission_index') or '').strip().upper()
        if mission and idx:
            template = profile['sensor_combine_mission_and_index'].get(mission)
            if template:
                return template.format(idx=idx)

    # Direct dict lookup
    if 'sensor_lookup' in profile and raw in profile['sensor_lookup']:
        return profile['sensor_lookup'][raw]

    # Regex + format string
    if 'sensor_lookup_regex' in profile:
        m = re.search(profile['sensor_lookup_regex'], raw, re.IGNORECASE)
        if m:
            try:
                return profile['sensor_format'].format(n=int(m.group(1)))
            except ValueError:
                return profile['sensor_format'].format(n=m.group(1))

    # Per-constellation regex
    if 'sensor_lookup_regex_per_constellation' in profile:
        constellation = resolve_constellation(extracted, profile)
        spec = profile['sensor_lookup_regex_per_constellation'].get(constellation)
        if spec:
            pattern, fmt = spec
            m = re.search(pattern, raw, re.IGNORECASE)
            if m:
                return fmt.format(n=m.group(1))

    return profile.get('sensor_default', 'Unknown')


def resolve_constellation(extracted, profile):
    if 'constellation' in profile:
        return profile['constellation']

    if 'constellation_from_mission' in profile:
        mission = str(extracted.get('mission') or '').upper()
        for pattern, name in profile['constellation_from_mission'].items():
            if re.search(pattern, mission, re.IGNORECASE):
                return name

    # NEW: lookup from sensor_id_raw (e.g., WV02 → WorldView)
    if 'constellation_from_sensor' in profile:
        sid = str(extracted.get('sensor_id_raw') or '').upper()
        for pattern, name in profile['constellation_from_sensor'].items():
            if re.search(pattern, sid, re.IGNORECASE):
                return name

    return 'Unknown'


def resolve_image_type(extracted, profile, file_path):
    """Determine image type (P, MS, HYPER) from profile rules."""
    if 'image_type' in profile:
        return profile['image_type']

    fn = Path(file_path).name
    for pat, img_type in profile.get('image_type_from_filename', {}).items():
        if re.search(pat, fn, re.IGNORECASE):
            return img_type

    # Band-count fallback
    n = extracted.get('num_bands')
    if isinstance(n, int):
        return 'P' if n == 1 else 'MS'

    return 'Unknown'

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
        filename = row['file_path']
        
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

def build_acquisition_summary(footprint_gdf):
    """
    Collapse per-file footprints into per-acquisition footprints.
    Each acquisition becomes one row with the unioned geometry of all its files.
    """
    from shapely.ops import unary_union
    
    def collapse(group):
        rep = group.iloc[0].copy()
        # Union all scene geometries into one acquisition footprint
        rep['geometry']      = unary_union(group['geometry'].tolist())
        rep['n_scenes']      = group['scene_id'].nunique()
        rep['n_files']       = len(group)
        rep['scenes']        = ','.join(sorted(group['scene_id'].dropna().unique()))
        rep['band_variants'] = ','.join(sorted(
            group.get('band_variant', pd.Series()).dropna().unique()))
        # Drop scene-specific fields
        for col in ['scene_id', 'band_variant', 'file_path', 'metadata_path']:
            if col in rep:
                rep[col] = None
        return rep
    
    acq_gdf = (footprint_gdf
               .groupby('acquisition_id', as_index=False, group_keys=False)
               .apply(collapse))
    
    return gpd.GeoDataFrame(acq_gdf, geometry='geometry', crs=footprint_gdf.crs)

def derive_acquisition_id(record, profile):
    """
    Get the acquisition ID from the field the profile says is canonical.
    Fall back to a composite key only if the canonical field is missing.
    """
    canonical_field = profile.get('acquisition_id_field')
    
    if canonical_field:
        canonical_value = record.get(canonical_field)
        if canonical_value and str(canonical_value).strip() not in ('', 'unknown', 'None'):
            return str(canonical_value)
    
    # Fallback for files where metadata couldn't be parsed
    # (returns a less-trusted composite key — flagged for review)
    sensor   = str(record.get('sensor') or 'UNK')
    date_str = ''
    for k in ('acquired', 'datetime'):
        v = record.get(k)
        if v:
            date_str = re.sub(r'[^\d]', '', str(v))[:14]
            break
    return f'FALLBACK_{sensor}_{date_str or "nodate"}'

def derive_scene_id(file_path):
    """Extract the tile/scene identifier from filename (R#C# pattern)."""
    fn = Path(file_path).name
    m = re.search(r'_(R\d+C\d+)', fn, re.IGNORECASE)
    return m.group(1).upper() if m else None

import pandas as pd
import re
from pathlib import Path

def derive_datetime_fields(record):
    """
    Build acquisition_datetime + year, month, day, doy from available metadata.
    Tries multiple sources: explicit timestamp fields → filename parsing → None.
    """
    # 1. Explicit timestamp fields (Tanager, Satellogic, etc.)
    dt_str = None
    for k in ('acquired', 'date_acquired', 'datetime', 'acquisition_datetime'):
        v = record.get(k)
        if v:
            dt_str = str(v)
            break

    # 2. Fallback: parse from filename
    if not dt_str:
        fn = Path(record['file_path']).name

        # Maxar/Legion: YYMMMDDHHMMSS  e.g., 25DEC29165051
        m = re.search(r'(\d{2})([A-Z]{3})(\d{2})(\d{6})', fn)
        if m:
            month_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                          'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
            yr, mn_str, dy, tm = m.groups()
            mn = month_map.get(mn_str.upper(), 1)
            yr = 2000 + int(yr)
            dt_str = f'{yr}-{mn:02d}-{int(dy):02d}T{tm[:2]}:{tm[2:4]}:{tm[4:6]}'

        # Standard YYYYMMDD anywhere in filename
        elif re.search(r'(\d{4})(\d{2})(\d{2})', fn):
            m2 = re.search(r'(\d{4})(\d{2})(\d{2})', fn)
            yr, mn, dy = m2.groups()
            dt_str = f'{yr}-{mn}-{dy}'

    # 3. Parse to pandas Timestamp
    dt = pd.to_datetime(dt_str, errors='coerce', utc=True) if dt_str else pd.NaT

    if pd.isna(dt):
        return {
            'acquisition_datetime': None,
            'year':  None,
            'month': None,
            'day':   None,
            'doy':   None,
        }

    return {
        'acquisition_datetime': dt.isoformat(),    # string for GPKG safety
        'year':  int(dt.year),
        'month': int(dt.month),
        'day':   int(dt.day),
        'doy':   int(dt.dayofyear),
    }
    
def process_file(file_path, profiles=SENSOR_PROFILES):
    """
    Process a single file: detect vendor, find metadata, parse, resolve attributes,
    return a dict ready to become a row in a GeoDataFrame.
    """
    profile_key = detect_vendor(file_path, profiles)
    if profile_key is None:
        return {'file_path': str(file_path), 'error': 'no profile matched'}

    profile = profiles[profile_key]
    metadata_path = find_metadata_file(file_path, profile)
    extracted = parse_metadata(metadata_path, profile)
    # NEW: also extract from filename
    extracted.update(extract_from_filename(file_path, profile))
    
    record = {
        'file_path':     str(file_path),
        'metadata_path': str(metadata_path) if metadata_path else None,
        'vendor_profile':profile_key,
        'affiliation':   profile.get('affiliation', 'Unknown'),
        'constellation': resolve_constellation(extracted, profile),
        'sensor':        resolve_sensor_name(extracted, profile),
        'image_type':    resolve_image_type(extracted, profile, file_path),
        **{k: v for k, v in extracted.items() if not k.startswith('_')},
        'band_variant': extracted.get('band_variant'),
        'tier':         extracted.get('tier'),
        **{k: v for k, v in extracted.items() if not k.startswith('_')},
    }

    # Geometry
    geom_src = profile['geometry_source']
    if geom_src['type'] == 'inline_geojson':
        record['geometry'] = extracted.get('_inline_geometry')
        record['_geom_crs'] = extracted.get('_inline_crs', 'EPSG:4326')
    elif geom_src['type'] == 'raster_bounds':
        # Defer to existing footprintlib for raster-derived geometry
        record['_needs_raster_footprint'] = True

    record['acquisition_id'] = derive_acquisition_id(record, profile)
    record['acquisition_id_source'] = ('canonical' if not record['acquisition_id'].startswith('FALLBACK_') else 'fallback')
    record['has_metadata']          = metadata_path is not None    # ← add this
    record['scene_id'] = derive_scene_id(file_path)
    record.update(derive_datetime_fields(record))    # ← adds year/month/day/doy
    
    return record

def process_files(file_list, profiles=SENSOR_PROFILES):
    """
    Process a list of files. Returns a GeoDataFrame.
    Files needing raster bounds are dispatched to existing footprintlib.raster_footprint.
    Files with inline geometry are returned directly.
    """
    inline_records = []
    raster_files   = []

    for fp in file_list:
        rec = process_file(fp, profiles)
        if rec.get('_needs_raster_footprint'):
            raster_files.append((fp, rec))
        elif rec.get('geometry') is not None:
            inline_records.append(rec)

    # Build inline-geometry GeoDataFrame
    inline_gdf = gpd.GeoDataFrame()
    if inline_records:
        inline_gdf = gpd.GeoDataFrame(
            inline_records,
            geometry='geometry',
            crs=inline_records[0].get('_geom_crs', 'EPSG:4326'),
        )

    # For raster-bounds files, hand off to existing logic
    raster_gdf = gpd.GeoDataFrame()
    if raster_files:
        # Run existing footprint code; merge the per-file metadata back in
        from multiprocessing import Pool
        from functools import partial
        # ...whatever footprintlib.raster_footprint expects
        with Pool(processes=4) as pool:
            geoms = pool.map(
                partial(
                    footprintlib.raster_footprint, # no
                    #footprintlib.raster_footprint_with_til_support,
                   DO_DATAMASK=False, 
                   GET_ONLY_DATASETMASK=False, 
                   R_READ_MODE='r', 
                   MANY_CRS=True),
                    [f for f, _ in raster_files])
        for (fp, rec), g in zip(raster_files, geoms):
            if g is not None:
                rec['geometry'] = g.geometry.iloc[0]   # adjust to footprintlib's return type
        raster_gdf = gpd.GeoDataFrame(
            [rec for _, rec in raster_files if rec.get('geometry') is not None],
            geometry='geometry', crs='EPSG:4326',
        )

    if len(inline_gdf) and len(raster_gdf):
        return gpd.GeoDataFrame(
            pd.concat([inline_gdf, raster_gdf], ignore_index=True),
            geometry='geometry', crs='EPSG:4326'
        )
    return inline_gdf if len(inline_gdf) else raster_gdf

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

def plot_site_coverage(site_name, footprint_gdf, sites_gdf, #BUF_KM, 
                       BUF_KM_TOTAL_FOR_DISPLAY, sites_buf_gdf=None, 
                       site_name_field = 'Site_Primary',
                       id_field = 'acquisition_id', 
                       affiliation_field = 'affiliation',
                       constellation_field = 'constellation',
                       figsize=(5, 5), ax=None):
    """
    Plot acquisition footprints for a specific site with ESRI gray basemap.
    
    Parameters:
    -----------
    site_name : str
        Name of the site to plot
    footprint_gdf : GeoDataFrame
        Acquisition footprints with 'Site_Primary' column
    sites_gdf : GeoDataFrame
        Sites boundaries
    sites_buf_gdf : GeoDataFrame, optional
        Buffered sites for display
    ax : matplotlib axis, optional
        Axis to plot on. If None, creates new figure.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import contextily as ctx
    import geopandas as gpd
    import numpy as np
    from matplotlib_scalebar.scalebar import ScaleBar
    
    # =========================================================================
    # COLOR DICTIONARY
    # =========================================================================
    cmap = plt.cm.turbo
    
    AFFILIATION_CONSTELLATION_COLORS = {
        'Maxar - Legion': cmap(0.1),
        'Maxar - WorldView': cmap(0.2),
        'Airbus - SPOT': cmap(0.35),
        'Airbus - Pleiades': cmap(0.5),
        'Airbus - Pleiades Neo': cmap(0.65),
        'Pixxel - Firefly': cmap(0.8),
        'Satellogic - MarkIV': cmap(0.9),
        'Satellogic - MarkV': cmap(0.95),
    }
    # =========================================================================
    
    # Filter data
    site = sites_gdf.loc[sites_gdf['Site Name'] == site_name].copy()
    footprints = footprint_gdf.loc[footprint_gdf[site_name_field] == site_name].copy()

    
    if len(site) == 0:
        print(f"Site '{site_name}' not found!")
        return
    
    if len(footprints) == 0:
        print(f"No acquisitions found for site '{site_name}'")
        return
    
    if False:
        print(f"Plotting {len(footprints)} acquisitions for {site_name}")
    
    # Convert to Web Mercator
    footprints_web = footprints.to_crs(epsg=3857)
    site_web = site.to_crs(epsg=3857)
    
    # Get buffer extent and find additional acquisitions
    footprints_buf = None
    if sites_buf_gdf is not None:
        site_buf = sites_buf_gdf.loc[sites_buf_gdf['Site Name'] == site_name].copy()
        if len(site_buf) > 0:
            site_buf_web = site_buf.to_crs(epsg=3857)
            
            footprints_all_web = footprint_gdf.to_crs(epsg=3857)
            footprints_in_buf = gpd.sjoin(footprints_all_web, site_buf_web, 
                                          how='inner', predicate='intersects')
            
            footprints_in_buf = footprints_in_buf.drop_duplicates(subset=id_field)
            footprints_buf = footprints_in_buf[~footprints_in_buf[id_field].isin(footprints_web[id_field])].copy()

            
            if False:
                print(f"Found {len(footprints_buf)} additional acquisitions in buffer zone")
    
    # Create figure and axis if not provided
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
        standalone = True
    else:
        fig = ax.get_figure()
        standalone = False
    
    # Create combined label for coloring
    footprints_web['combined_label'] = (
        footprints_web[affiliation_field].astype(str) + ' - ' + 
        footprints_web[constellation_field].astype(str)
    )
    
    # Get ALL unique combinations
    all_combos = set(footprints_web['combined_label'].unique())
    if footprints_buf is not None and len(footprints_buf) > 0:
        footprints_buf['combined_label'] = (
            footprints_buf[affiliation_field].astype(str) + ' - ' + 
            footprints_buf[constellation_field].astype(str)
        )
        all_combos.update(footprints_buf['combined_label'].unique())
    
    # Create color map
    all_combos = sorted(list(all_combos))
    color_map = {}
    
    cmap_idx = 0
    for combo in all_combos:
        if combo in AFFILIATION_CONSTELLATION_COLORS:
            color_map[combo] = AFFILIATION_CONSTELLATION_COLORS[combo]
        else:
            color_map[combo] = cmap(cmap_idx / max(len(all_combos), 1))
            cmap_idx += 1
    
    # Plot each affiliation-constellation group (main site)
    legend_handles_site = []
    for combo in footprints_web['combined_label'].unique():
        subset = footprints_web[footprints_web['combined_label'] == combo]
        subset.plot(ax=ax, 
                    facecolor=color_map[combo], 
                    edgecolor='black',
                    alpha=0.3,
                    linewidth=2)
        
        patch = mpatches.Patch(facecolor=color_map[combo], edgecolor=color_map[combo],
                               alpha=0.3, label=f"{combo} (n={len(subset)})")
        legend_handles_site.append(patch)
    
    # Plot acquisitions in buffer zone
    legend_handles_buffer = []
    if footprints_buf is not None and len(footprints_buf) > 0:
        unique_combos_buf = footprints_buf['combined_label'].unique()
        
        for combo in unique_combos_buf:
            subset = footprints_buf[footprints_buf['combined_label'] == combo]
            color = color_map[combo]
            
            subset.plot(ax=ax, 
                        facecolor=color, 
                        edgecolor='black',
                        alpha=0.15,
                        linewidth=1, linestyle='dotted',
                        hatch='///')
            
            patch = mpatches.Patch(facecolor=color, edgecolor='black',
                                   alpha=0.15, hatch='///',
                                   label=f"{combo} (n={len(subset)})")
            legend_handles_buffer.append(patch)
    
    # Plot buffer
    if sites_buf_gdf is not None:
        site_buf = sites_buf_gdf[sites_buf_gdf['Site Name'] == site_name].to_crs(epsg=3857)
        if len(site_buf) > 0:
            site_buf.boundary.plot(ax=ax, color='gray', linewidth=1.5, 
                                   linestyle='dotted', alpha=0.6, zorder=9)
    
    
    # Plot site boundary
    site_web.boundary.plot(ax=ax, color='red', linewidth=2, 
                           linestyle='-', 
                           label=f'Overlapping {site_name} site', 
                           zorder=10)
    
    # Add basemap
    ctx.add_basemap(ax, source=ctx.providers.Esri.WorldGrayCanvas, attribution_size=8)
    
    # Format
    ax.set_title(f'{site_name}\n{len(footprints)} acquisitions', 
                 fontsize=15, fontweight='bold', pad=0)

    # Add scalebar (ADD THIS)
    scalebar = ScaleBar(1, location='lower right', box_alpha=0.8, 
                       scale_loc='top', font_properties={'size': 10})
    ax.add_artist(scalebar)
    
    # Create primary legend for main site acquisitions
    legend1 = ax.legend(handles=legend_handles_site, 
                       loc='upper left', 
                       fontsize=9, 
                       framealpha=0.95, 
                       title=f'Overlapping {site_name} site',
                       title_fontsize=10)
    ax.add_artist(legend1)  # Add first legend back to plot
    
    # Create secondary legend for buffer zone acquisitions (if any)
    if legend_handles_buffer:
        legend2 = ax.legend(handles=legend_handles_buffer, 
                           loc='lower left', 
                           fontsize=9, 
                           framealpha=0.95,
                           title=f'Nearby {site_name} site (within {BUF_KM_TOTAL_FOR_DISPLAY} km )',
                           title_fontsize=10)
    
    ax.set_xticks([])
    ax.set_yticks([])
    
    # Only show/tight_layout if standalone
    if standalone:
        plt.tight_layout()
        plt.show()
    
    return fig, ax

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
            print(f"Warning: Could not procesexplodeds column '{col}': {e}")
            continue
    
    return gdf_export

def link_acquisitions_to_sites(footprint_gdf, sites_gdf, buffer_distance=0, 
                               site_name_col='Site Name'):
    """
    Link acquisition-level footprints to sites using spatial join.
    
    This function:
    1. Buffers sites by specified distance
    2. Spatially joins acquisitions to sites (finds intersections)
    3. Creates mapping of acquisition_id to list of associated sites
    4. Merges site information back to footprint_gdf
    
    Parameters:
    -----------
    footprint_gdf : GeoDataFrame
        Acquisition-level footprints (must have 'acquisition_id' column)
    sites_gdf : GeoDataFrame
        Sites polygons
    buffer_distance : float, default=0
        Distance to buffer sites (in units of sites_gdf CRS)
    site_name_col : str, default='Site Name'
        Column name containing site names in sites_gdf (note: 'Site Name' with space)
    
    Returns:
    --------
    tuple: (footprint_with_sites, acquisition_site_mapping)
        - footprint_with_sites: GeoDataFrame with added columns:
            - 'Site_Primary': primary site name for each acquisition (1st alphabetically)
            - 'Site_Secondary': secondary site name (2nd alphabetically), None if only 1 site
            - 'Site_Tertiary': tertiary site name (3rd alphabetically), None if <3 sites
            - 'num_sites': count of sites per acquisition
            - 'sites': list of all site names for each acquisition
        - acquisition_site_mapping: DataFrame mapping acquisition_id to sites
    """
    import geopandas as gpd
    
    # Validate inputs
    if 'acquisition_id' not in footprint_gdf.columns:
        raise ValueError("footprint_gdf must have 'acquisition_id' column")
    
    if site_name_col not in sites_gdf.columns:
        raise ValueError(f"sites_gdf does not have column '{site_name_col}'. Available columns: {sites_gdf.columns.tolist()}")
    
    # Check if CRS is geographic (degrees) - warn about buffering
    if sites_gdf.crs.is_geographic:
        print(f"WARNING: CRS is geographic ({sites_gdf.crs}). Buffer distance will be in degrees.")
        print(f"Consider reprojecting to a projected CRS for accurate buffering.")
    
    # Check CRS match
    if footprint_gdf.crs != sites_gdf.crs:
        print(f"WARNING: CRS mismatch. Footprints: {footprint_gdf.crs}, Sites: {sites_gdf.crs}")
        print(f"Reprojecting sites to match footprints CRS...")
        sites_gdf = sites_gdf.to_crs(footprint_gdf.crs)
    
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
    # Group by acquisition_id and aggregate the site names
    acquisition_site_mapping = joined.groupby('acquisition_id')[site_name_col].apply(
        lambda x: sorted(list(x.unique()))  # Sort alphabetically for consistency
    ).reset_index()
    acquisition_site_mapping.columns = ['acquisition_id', 'sites']
    
    # Add count of sites per acquisition
    acquisition_site_mapping['num_sites'] = acquisition_site_mapping['sites'].apply(len)
    
    # Add primary, secondary, and tertiary sites (1st, 2nd, 3rd alphabetically)
    acquisition_site_mapping['Site_Primary'] = acquisition_site_mapping['sites'].apply(
        lambda x: x[0] if len(x) > 0 else None
    )
    acquisition_site_mapping['Site_Secondary'] = acquisition_site_mapping['sites'].apply(
        lambda x: x[1] if len(x) > 1 else None
    )
    acquisition_site_mapping['Site_Tertiary'] = acquisition_site_mapping['sites'].apply(
        lambda x: x[2] if len(x) > 2 else None
    )
    
    # Merge back to original footprint_gdf to ensure we keep all acquisitions
    footprint_with_sites = footprint_gdf.merge(
        acquisition_site_mapping[['acquisition_id', 'Site_Primary', 'Site_Secondary', 
                                   'Site_Tertiary', 'num_sites', 'sites']],
        on='acquisition_id',
        how='left'  # Keep all acquisitions, even those without sites
    )
    
    # Fill NaN for acquisitions not near any site
    footprint_with_sites['Site_Primary'] = footprint_with_sites['Site_Primary'].fillna('Not CSDA Eval Site')
    # For Secondary and Tertiary, NaN is fine - they represent "no secondary/tertiary site"
    # But if you want to explicitly set them, use np.nan or leave as-is
    footprint_with_sites['num_sites'] = footprint_with_sites['num_sites'].fillna(0).astype(int)
    footprint_with_sites['sites'] = footprint_with_sites['sites'].apply(
        lambda x: x if isinstance(x, list) else []
    )
    
    # Verify no duplicates (should have one row per acquisition)
    n_duplicates = footprint_with_sites['acquisition_id'].duplicated().sum()
    if n_duplicates > 0:
        print(f"WARNING: Found {n_duplicates} duplicate acquisition_ids in result")
        print("This may indicate duplicate acquisitions in input data")
    
    print(f"\nSummary:")
    print(f"  Total acquisitions: {len(footprint_with_sites)}")
    print(f"  Acquisitions intersecting sites: {(footprint_with_sites['num_sites'] > 0).sum()}")
    print(f"  Acquisitions NOT intersecting sites: {(footprint_with_sites['num_sites'] == 0).sum()}")
    print(f"  Single-site acquisitions: {(footprint_with_sites['num_sites'] == 1).sum()}")
    print(f"  Multi-site acquisitions (2+ sites): {(footprint_with_sites['num_sites'] > 1).sum()}")
    print(f"  Acquisitions covering 3+ sites: {(footprint_with_sites['num_sites'] > 2).sum()}")
    
    return footprint_with_sites.to_crs(4326), acquisition_site_mapping

def create_comprehensive_summary(footprint_with_sites, acquisition_site_mapping, 
                                   site_name_col='site_primary', date_col='acquisition_date',
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
        date_col: ['min', 'max']
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
        date_col: ['min', 'max']
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
            footprint_with_sites[['acquisition_id', 'affiliation', 'constellation', 'sensor', 'image_type', date_col]],
            on='acquisition_id',
            how='left'
        )
        
        # Summary counting each acquisition for each site it covers
        summary_all_sites = detailed.groupby(
            ['Site_Name', 'affiliation', 'constellation', 'sensor', 'image_type']
        ).agg({
            'acquisition_id': 'nunique',
            date_col: ['min', 'max']
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

def make_CSDA_footprints_map(gdf, MAP=None, width='100%', height='25%', ACQS=True, site_name_col='Primary_Site',
                            TOOLTIP_FIELDS_LIST = ['affiliation','constellation','sensor','acquisition_id','base_image_name','band_combo','year','month','day']
                            ):

    Map_Figure=Figure()
    combined_gdf_list = []    
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
    #           'darkred', 'lightred', 'darkblue', 'lightblue', 'darkgreen', 'lightgreen', 'cadetblue',
    #           'darkpurple', 'white', 'lightgray']
    # Create colors
    colors = plt.cm.plasma(np.linspace(0, 1, n_combinations))

    # Convert to hex colors for Folium
    colors = [mcolors.to_hex(color) for color in colors]
    color_dict = {}
    
    # Create a feature group for each combined value
    for i, combined_val in enumerate(combined_values):
        color = colors[i % len(colors)]
        color_dict[combined_val] = color
        
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
        combined_gdf_list.append(combined_gdf)
    
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

    # Create and write a QML color dict file for QGIS
    combined_gdf = pd.concat(combined_gdf_list)
    combined_gdf.to_file('footprints_CSDA_eval_ACQUISITIONS_combined_label_version.geojson')
    create_qgis_qml(color_dict, 'footprints_CSDA_eval_ACQUISITIONS_combined_label_color_dict.qml', field_name='combined_label')    
    
    return(m)

# Function to create QGIS QML from hex colors
def create_qgis_qml(color_dict, output_qml_path, field_name='combined_label'):
    """
    Create a QGIS QML style file for categorized symbology
    
    Parameters:
    -----------
    color_dict : dict
        Dictionary mapping category values to hex color codes
    output_qml_path : str
        Path where QML file should be saved
    field_name : str
        Name of the field to use for categorization
    """
    
    def hex_to_rgb(hex_color):
        """Convert hex color to R,G,B string"""
        hex_color = hex_color.lstrip('#')
        return ','.join(str(int(hex_color[i:i+2], 16)) for i in (0, 2, 4))
    
    # Start QML XML
    qml_content = '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology">
  <renderer-v2 type="categorizedSymbol" attr="{field_name}" symbollevels="0" forceraster="0">
    <categories>
'''.format(field_name=field_name)
    
    # Add categories
    for i, (label, hex_color) in enumerate(color_dict.items()):
        category = '''      <category symbol="{i}" value="{label}" label="{label}" render="true"/>
'''.format(i=i, label=label)
        qml_content += category
    
    qml_content += '''    </categories>
    <symbols>
'''
    
    # Add symbols
    for i, (label, hex_color) in enumerate(color_dict.items()):
        rgb = hex_to_rgb(hex_color)
        
        symbol = '''      <symbol type="fill" name="{i}" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" locked="0" enabled="1">
          <prop k="color" v="{rgb},255"/>
          <prop k="outline_color" v="35,35,35,255"/>
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0.26"/>
          <prop k="style" v="solid"/>
        </layer>
      </symbol>
'''.format(i=i, rgb=rgb)
        qml_content += symbol
    
    qml_content += '''    </symbols>
  </renderer-v2>
</qgis>
'''
    
    # Write to file
    with open(output_qml_path, 'w') as f:
        f.write(qml_content)
    
    print(f"QML file created: {output_qml_path}")

# CSDA Downloading
from concurrent.futures import ThreadPoolExecutor, as_completed

def _process_one_item(item, client):
    info = get_product_info_smart(item, client)
    info['item_id'] = item.id
    return info

def download_all_assets(item, client, output_dir, skip=None):
    """
    Download every asset of a STAC item to a directory.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    skip = set(skip or [])
    
    downloaded = {}
    for key, asset in item.assets.items():
        if key in skip:
            continue
        
        # Use the asset's original filename
        filename = asset.href.split('/')[-1]
        local_path = output_dir / filename
        
        try:
            client.download_item(item, key, str(local_path))
            downloaded[key] = local_path
            print(f'  ✓ {key:20s}  → {filename}')
        except Exception as e:
            print(f'  ✗ {key:20s}  {e}')
    
    return downloaded
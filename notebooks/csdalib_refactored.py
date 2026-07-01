# csdalib_refactored.py
import re, json, glob, os
from pathlib import Path
import xml.etree.ElementTree as ET
import geopandas as gpd
from shapely.geometry import shape

import pandas as pd

from sensor_profiles import SENSOR_PROFILES
import os, sys
sys.path.append('/home/pmontesa/code/geoscitools')
import footprintlib

def _get_nested(d, dotted_path):
    """Walk dotted path through nested dict, return None if missing."""
    cur = d
    for key in dotted_path.split('.'):
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
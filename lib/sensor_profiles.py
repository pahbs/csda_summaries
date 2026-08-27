"""
sensor_profiles.py
==================

Profile-driven configuration for the CSDA imagery footprint and metadata
dispatcher (csdalib_refactored.py).

Each entry in SENSOR_PROFILES describes one vendor/sensor family. Adding
a new sensor requires only a new profile entry — no changes to the
dispatcher code.

----------------------------------------------------------------------
SCHEMA REFERENCE
----------------------------------------------------------------------

A profile is a dict with the following keys. Required keys are marked
with [REQUIRED]; all others are optional.

----------------------------------------------------------------------
TOP-LEVEL ATTRIBUTES
----------------------------------------------------------------------

'affiliation' : str  [REQUIRED]
    Vendor or organization name.
    Examples: 'Maxar', 'Airbus', 'Pixxel', 'Planet', 'Satellogic'

'constellation' : str  [optional]
    Constellation name. If set, applied to every record from this profile.
    If not set, must be resolvable via 'constellation_from_mission' or
    'constellation_from_sensor' (see below).
    Examples: 'Legion', 'Pleiades Neo', 'Firefly', 'Aleph-1', 'Tanager'

'acquisition_id_field' : str  [REQUIRED]
    Name of the *record field* (NOT the XML tag) whose value should be
    used as the canonical acquisition_id. This field must be populated
    by the profile's 'fields' block (from metadata) or 'extract_from_filename'
    block (from filename).
    Examples: 'catid', 'image_id', 'strip_id'

----------------------------------------------------------------------
DETECTION
----------------------------------------------------------------------

'detect' : dict  [REQUIRED]
    How to recognize a file belongs to this vendor.

    'filename_patterns' : list of regex strings  [REQUIRED]
        Each pattern is tested against the file's basename.
        First profile whose pattern matches wins, so order matters
        if vendors share filename prefixes.
        Use case-insensitive matches.

    'metadata_glob' : str  [optional, documentation only]
        Hint about what metadata files this vendor delivers. Not used
        by the dispatcher logic; helpful as a comment for future readers.

----------------------------------------------------------------------
METADATA LOCATION
----------------------------------------------------------------------

'metadata_finder' : dict  [REQUIRED]
    How to locate the metadata sidecar given an image file path.

    'type' : str  [REQUIRED]
        One of:
            'sibling'             — metadata in the same directory as the image
            'sibling_strip_tile'  — like 'sibling' but strip tile pattern from base
            'self'                — the input file IS the metadata file (e.g., GeoJSON)

    'pattern' : str  [REQUIRED for sibling/sibling_strip_tile types]
        Filename pattern with placeholders. Tokens supported:
            {base}          — image filename without extension
            {base_clean}    — base with common suffixes (_CLOUD_N, _L1A) stripped
            {base_no_tile}  — base with tile pattern (R#C#) stripped
            {base_dim}      — base with IMG_ prefix removed and tile/band stripped
                              (Airbus IMG_*.TIF → DIM_*.XML pairing)

    'tile_pattern' : str  [optional]
        Regex defining the tile suffix to strip for {base_no_tile}.
        Default: r'_R\\d+C\\d+'

    'fallback_glob' : str  [optional]
        If the exact pattern fails, glob the directory and use the first match.
        Useful for vendors with variable filename suffixes.

----------------------------------------------------------------------
METADATA PARSING
----------------------------------------------------------------------

'metadata_format' : str  [REQUIRED]
    One of: 'xml', 'json'

'fields' : dict  [REQUIRED]
    Maps a *standardized record field name* (the dispatcher's contract)
    to instructions for extracting it from metadata.

    Each entry's value is one of:

      A) A string (simple JSON path or XML tag):
            'image_id': 'id'                          # JSON top-level
            'sensor_id_raw': 'properties.satellite_id' # JSON nested
            'sensor': 'MISSION'                       # XML tag (any depth)

      B) A dict with multiple-source fallback:
            'catid': {
                'tag':           'Order_Id',
                'fallback_tags': ['Scene_Id', 'imageId'],
                'cast':          'int'                # optional: 'int', 'float'
            }

    Standardized field names used across profiles:
        sensor_id_raw    — raw vendor sensor ID (e.g., 'LG01', 'newsat10', 'PHR')
        mission          — mission/constellation string (Airbus DIMAP)
        mission_index    — satellite number (Airbus DIMAP: '1A', '6', etc.)
        catid            — vendor catalog/order ID
        image_id         — vendor image ID (where distinct from catid)
        strip_id         — Planet Tanager / Satellogic strip identifier
        acquired         — acquisition datetime string
        product_level    — processing level (L1B, L1C, L2A, ORTHO, etc.)
        num_bands        — number of bands (int)
        gsd              — ground sampling distance (m)
        cloud_percent    — cloud cover %
        sun_elevation, sun_azimuth, view_angle, satellite_azimuth — geometry

----------------------------------------------------------------------
FILENAME EXTRACTION (fallback when metadata is missing)
----------------------------------------------------------------------

'extract_from_filename' : dict  [optional]
    Patterns to extract additional fields directly from the filename.
    Useful as a fallback when metadata files are missing.

    Each entry's value is a regex with one or more capture groups.
    The first captured group becomes the field value.

    Example:
        'extract_from_filename': {
            'image_id':     r'FF0\\d_\\d{8}_\\d+_(\\d+)_[LP]',
            'band_variant': r'_(RGB|NED|RGBN|PMS|PAN)_R\\d+C\\d+',
        }

----------------------------------------------------------------------
GEOMETRY SOURCE
----------------------------------------------------------------------

'geometry_source' : dict  [REQUIRED]
    Where the footprint geometry comes from.

    'type' : str  [REQUIRED]
        One of:
            'raster_bounds'    — open the raster and compute footprint from bounds
                                  (uses existing footprintlib.raster_footprint)
            'inline_geojson'   — geometry is in the metadata JSON itself

    For 'inline_geojson':
        'path' : str   — dotted path to the geometry object in the JSON
                          Example: 'geometry'  (top-level GeoJSON spec)
        'crs'  : str   — CRS of the inline geometry
                          Default: 'EPSG:4326'

----------------------------------------------------------------------
SENSOR NAME RESOLUTION
----------------------------------------------------------------------

The dispatcher tries these in order until one succeeds. Use whichever
matches your vendor's metadata conventions.

'sensor_lookup' : dict  [optional]
    Direct mapping from raw sensor ID → standardized name.
    Example:
        'sensor_lookup': {
            'WV01': 'WorldView-1',
            'WV02': 'WorldView-2',
            ...
        }

'sensor_lookup_regex' : str  [optional]
    Regex applied to the raw sensor string with one capture group.
    Used together with 'sensor_format' to produce the final name.
    Example (Legion):
        'sensor_lookup_regex': r'LG0?([1-6])'
        'sensor_format':       'LG0{n}'
        →  'LG2' or 'LG02' → 'LG02'

'sensor_format' : str  [REQUIRED with sensor_lookup_regex]
    Format string with one '{n}' placeholder (filled from the regex match).
    Use {n:02d} for zero-padding (e.g., Satellogic SN01–SN50).

'sensor_lookup_regex_per_constellation' : dict  [optional]
    Per-constellation regex/format pairs. Used for vendors whose sensor
    naming depends on which constellation is in play (Airbus DIMAP).
    Example:
        'sensor_lookup_regex_per_constellation': {
            'Pleiades Neo': (r'PNEO\\s*([1-6])',    'PNEO{n}'),
            'Pleiades':     (r'PHR\\s*([12][AB])',  'PHR{n}'),
            'SPOT':         (r'SPOT\\s*([67])',     'SPOT{n}'),
        }

'sensor_combine_mission_and_index' : dict  [optional]
    For vendors where the sensor name is built by combining two metadata
    fields (Airbus DIMAP combines <MISSION> + <MISSION_INDEX>).
    Example:
        'sensor_combine_mission_and_index': {
            'PHR':  'PHR{idx}',     # PHR + 1B → PHR1B
            'SPOT': 'SPOT{idx}',    # SPOT + 6 → SPOT6
            'PNEO': 'PNEO{idx}',    # PNEO + 3 → PNEO3
        }

'sensor_default' : str  [optional]
    Fallback when none of the above resolves a sensor.
    Example: 'Legion', 'Maxar', 'Tanager'

----------------------------------------------------------------------
CONSTELLATION RESOLUTION
----------------------------------------------------------------------

Used when 'constellation' isn't a fixed value at the top of the profile
(i.e., one profile handles multiple constellations).

'constellation_from_mission' : dict  [optional]
    Regex → constellation name. Tested against extracted['mission'].
    Example:
        'constellation_from_mission': {
            r'^PNEO':           'Pleiades Neo',
            r'^PHR|^PLEIADES':  'Pleiades',
            r'^SPOT':           'SPOT',
        }

'constellation_from_sensor' : dict  [optional]
    Regex → constellation name. Tested against extracted['sensor_id_raw'].
    Useful for Maxar legacy where the SATID determines constellation.
    Example:
        'constellation_from_sensor': {
            r'^WV': 'WorldView',
            r'^GE': 'GeoEye',
            r'^QB': 'QuickBird',
        }

----------------------------------------------------------------------
IMAGE TYPE RESOLUTION
----------------------------------------------------------------------

'image_type' : str  [optional]
    Fixed image type for all files from this profile.
    Example: 'HYPER' for Pixxel/Tanager hyperspectral.

'image_type_from_filename' : dict  [optional]
    Regex → image type. Tested against the filename. First match wins.
    Example:
        'image_type_from_filename': {
            r'-P3DS':  'P',     # Legion panchromatic
            r'-M3DS':  'MS',    # Legion multispectral
            r'-S3DS':  'MS',    # Legion stereo bundle (multispectral)
        }

----------------------------------------------------------------------
COMPLETE MINIMAL EXAMPLE
----------------------------------------------------------------------

'new_vendor': {
    'affiliation':          'NewCo',
    'constellation':        'NewSat',
    'acquisition_id_field': 'image_id',

    'detect': {
        'filename_patterns': [r'^NS\d+_'],
    },
    'metadata_finder': {
        'type':    'sibling',
        'pattern': '{base}.json',
    },
    'metadata_format': 'json',
    'fields': {
        'image_id':       'id',
        'sensor_id_raw':  'properties.satellite_id',
        'acquired':       'properties.datetime',
        'gsd':            'properties.gsd',
        'cloud_percent':  'properties.cloud_cover',
    },
    'geometry_source': {
        'type': 'inline_geojson',
        'path': 'geometry',
        'crs':  'EPSG:4326',
    },
    'sensor_lookup': {
        'newsat-1': 'NS-1',
        'newsat-2': 'NS-2',
    },
    'sensor_default': 'NewSat',
    'image_type':     'MS',
},

----------------------------------------------------------------------
DISPATCHER OUTPUT
----------------------------------------------------------------------

Every record returned by the dispatcher has these standard fields,
regardless of vendor profile:

    file_path              — path to the source raster or metadata file
    metadata_path          — path to the metadata sidecar (or None)
    vendor_profile         — key of the matched SENSOR_PROFILES entry
    affiliation            — from profile
    constellation          — from profile (or resolved dynamically)
    sensor                 — resolved sensor name
    image_type             — 'P', 'MS', 'HYPER', or 'Unknown'
    acquisition_id         — from profile's acquisition_id_field
    acquisition_id_source  — 'canonical' (from metadata) or 'fallback'
    has_metadata           — True if a metadata file was found
    scene_id               — tile identifier (R#C#) from filename
    acquisition_datetime   — ISO timestamp string
    year, month, day, doy  — date components
    geometry               — Shapely polygon (EPSG:4326)

Plus any additional fields declared in the profile's 'fields' or
'extract_from_filename' blocks.

----------------------------------------------------------------------
TROUBLESHOOTING NEW PROFILES
----------------------------------------------------------------------

When adding a new vendor profile, work through these steps:

  1. DETECTION
     Run:  detect_vendor(sample_file_path)
     Should return your new profile's key.
     If None → fix 'detect.filename_patterns' regex.

  2. METADATA LOCATION
     Run:  find_metadata_file(sample_file_path, SENSOR_PROFILES['new'])
     Should return the path to the metadata sidecar.
     If None → fix 'metadata_finder.pattern' or add a 'fallback_glob'.

  3. FIELD EXTRACTION
     Run:  process_file(sample_file_path)
     Inspect the returned dict.
     Confirm sensor, constellation, and acquisition_id are populated
     correctly. If any are 'Unknown' or fallback-derived, examine which
     field in 'fields' isn't matching the metadata structure.

  4. METADATA INSPECTION HELPERS
     For XML: walk the file with ElementTree and print all populated
     leaf tags to discover the right tag names:

        import xml.etree.ElementTree as ET
        root = ET.parse(xml_path).getroot()
        for elem in root.iter():                          # strip namespaces
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]
        def walk(elem, path=''):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            cur = f'{path}/{tag}' if path else tag
            if not list(elem) and elem.text and elem.text.strip():
                print(f'  {cur}: {elem.text.strip()[:80]}')
            for child in elem:
                walk(child, cur)
        walk(root)

     For JSON: just print the parsed structure:
        import json; print(json.dumps(json.load(open(p)), indent=2))

  5. ACQUISITION_ID VALIDATION
     After running the dispatcher, check:
        df['acquisition_id_source'].value_counts()
     Any 'fallback' rows mean the canonical metadata ID wasn't found.
     Either fix the profile's field extraction, or accept that some
     deliveries have incomplete metadata (flag via has_metadata=False).

----------------------------------------------------------------------
DESIGN PRINCIPLES
----------------------------------------------------------------------

1. Vendor-specific knowledge stays in this file. The dispatcher in
   csdalib_refactored.py is vendor-agnostic.

2. If you find yourself writing `if vendor == 'X'` in the dispatcher,
   the profile schema needs another option — not the dispatcher.

3. Filenames are unreliable. Metadata is canonical. Use
   'extract_from_filename' only as a fallback for known gaps in
   vendor deliveries (e.g., missing XMLs).

4. Profile ORDER MATTERS during detection. More specific profiles
   should come before more general ones (e.g., 'legion' before
   'maxar_legacy' so Legion's 3DS pattern is checked first).

5. Every profile should target a unique 'acquisition_id_field'. Two
   profiles can map to the same standardized field name (e.g., 'catid')
   as long as each profile's 'fields' block populates it from the
   correct vendor-specific tag.

6. Adding a new vendor = one new entry in SENSOR_PROFILES. No
   dispatcher edits. If a vendor doesn't fit cleanly, that's a signal
   the schema needs extending — extend it generically, not via a
   vendor-specific branch.

======================================================================
"""

# ---- SENSOR_PROFILES dict starts below ----

SENSOR_PROFILES = {

    # ----- Planet Tanager (NEW — JSON metadata, geometry inline) -----
    'tanager': {
        'acquisition_id_field': 'image_id',
        'affiliation': 'Planet',
        'constellation': 'Tanager',

        # How to detect this vendor from a file path
        'detect': {
            'filename_patterns':  [r'_basic_radiance\.h5$', r'^.*_4\d{3}_'],
            'metadata_glob':      '*.json',
            'metadata_match_key': ('properties.item_type', 'TanagerScene'),  # key + value match
        },

        # How to locate the metadata file given an image file path
        'metadata_finder': {
            'type':            'sibling',          # in same dir
            'pattern':         '{base}.json',      # {base} = filename without extension
            'fallback_glob':   '*.json',           # if exact match fails, glob and filter
        },

        # Parsing rules — maps standard fields to JSON paths
        'metadata_format': 'json',
        'fields': {
            'image_id':         'id',
            'sensor_id_raw':    'properties.satellite_id',
            'strip_id':         'properties.strip_id',
            'acquired':         'properties.acquired',
            'cloud_percent':    'properties.cloud_percent',
            'gsd':              'properties.gsd',
            'sun_elevation':    'properties.sun_elevation',
            'sun_azimuth':      'properties.sun_azimuth',
            'view_angle':       'properties.view_angle',
            'satellite_azimuth':'properties.satellite_azimuth',
            'item_type':        'properties.item_type',
            'product_level':    'properties.publishing_stage',
            'quality_category': 'properties.quality_category',
        },

        # Geometry — directly from JSON, no raster opening required
        'geometry_source': {
            'type':       'inline_geojson',
            'path':       'geometry',
            'crs':        'EPSG:4326',
        },

        # Sensor name resolution from sensor_id_raw
        'sensor_lookup': {
            '4001': 'Tanager-1',
            '4002': 'Tanager-2',
            '4003': 'Tanager-3',
        },
        'sensor_default': 'Tanager',

        # Image type
        'image_type': 'HYPER',   # Tanager is hyperspectral
    },

    # ----- Maxar Legion (XML metadata, raster geometry) -----
    'legion': {
        'acquisition_id_field': 'catid',
        'affiliation': 'Maxar',
        'constellation': 'Legion',

        'detect': {
            'filename_patterns': [
                r'-[PM]1BS-',        # M1BS, P1BS
                r'-[PMS]3DS_R\d+C\d+',       # M3DS, P3DS, S3DS (standard)
                r'-[PM]2[AS]S_R\d+C\d+',      # M2AS, P2AS, M2SS, P2SS (legacy Legion)
                r'\d{2}[A-Z]{3}\d{8}-[PMS][23][AD]S',
            ],
        },

        'metadata_finder': {
            'type':    'sibling_strip_tile',
            'pattern': '{base_no_tile}.XML',         # remove R#C# from base, then .XML
            'tile_pattern': r'_R\d+C\d+',
        },

        'metadata_format': 'xml',
        'fields': {
                'sensor_id_raw': {'tag': 'SATID', 'fallback_tags': ['satId', 'platformName']},
                'catid':         {'tag': 'CATID',                         # ← changed back to catid
                                  'fallback_tags': ['PRODUCTORDERID']}, 
                'product_level': {'tag': 'PRODUCTLEVEL'},
                'product_type': {'tag': 'PRODUCTTYPE'},
                'radiometric_type': {'tag': 'RADIOMETRICENHANCEMENT'},
                'gsd':             {'tag': 'MEANCOLLECTEDGSD'},
                'cloud_percent':   {'tag': 'CLOUDCOVER'},
                'sun_elevation':       {'tag': 'MEANSUNEL', 'cast': 'int'},
                'sun_azimuth':         {'tag': 'MEANSUNAZ', 'cast': 'int'},
                'satellite_azimuth':   {'tag': 'MEANSATAZ', 'cast': 'int'},
                'satellite_elevation': {'tag': 'MEANSATEL', 'cast': 'int'},
                'view_angle':          {'tag': 'MEANOFFNADIRVIEWANGLE', 'cast': 'int'},
        },
        # Geometry comes from the raster bounds (existing footprint logic)
        'geometry_source': {
            'type': 'raster_bounds',
        },

        'sensor_lookup_regex': r'LG0?([1-6])',
        'sensor_format':       'LG0{n}',
        'sensor_default':      'Legion',

        'image_type_from_filename': {
            r'-P3DS':  'P',
            r'-M3DS':  'MS',
            r'-S3DS':  'MS',
            r'-P2[AS]S': 'P',                 # ← add
            r'-M2[AS]S': 'MS',                # ← add
        },
        'extract_from_filename': {
            'band_variant': r'_(RGB|NED|RGBN|BGRN|PMS|PAN|MS|MS-FS|P)_R\d+C\d+',
            'tier':         r'_(STD|HD|STE)_',     # processing tier
        },
    },

    # ------- Maxar's older Maxar IMD/XML metadata format
    'maxar_imd': {
        'acquisition_id_field': 'catid',
        'affiliation': 'Maxar',
        'detect': {
            'filename_patterns': [r'-[PM]2[AS]S_R\d+C\d+',
                                  r'\d{2}[A-Z]{3}\d{8}-[PM]2[AS]S','Worldview'],
            'metadata_glob':     '*.XML',
        },
        'metadata_finder': {
            'type':         'sibling_strip_tile',
            'pattern':      '{base_no_tile}.XML',
            'tile_pattern': r'_R\d+C\d+',
            'fallback_glob':'*.XML',
        },
        'metadata_format': 'xml',
        'fields': {
            'sensor_id_raw': {'tag': 'SATID', 'fallback_tags': ['platformName']},
            'catid':         {'tag': 'CATID', 'fallback_tags': ['imageId']},
            'product_level': {'tag': 'PRODUCT_LEVEL'},
        },
        'geometry_source': {'type': 'raster_bounds'},
        'sensor_lookup': {
            'WV01':'WorldView-1', 'WV02':'WorldView-2',
            'WV03':'WorldView-3', 'WV04':'WorldView-4',
            'GE01':'GeoEye-1',
            'QB02':'QuickBird',
        },
        'sensor_default': 'Maxar',
        'image_type_from_filename': {
            r'-P[123][AS]S': 'P',
            r'-M[123][AS]S': 'MS',
        },
        # Constellation derived from sensor_id_raw
        'constellation_from_sensor': {
            r'^WV': 'WorldView',
            r'^GE': 'GeoEye',
            r'^QB': 'QuickBird',
        },
    },

    # ----- Maxar legacy WorldView/GeoEye/QuickBird (-S2DS, -P2AS, -M2AS, etc.) -----
    'maxar_legacy': {
        'acquisition_id_field': 'catid',
        'affiliation': 'Maxar',
        'detect': {
                'filename_patterns': [
                    # Match Maxar archive format BUT exclude Legion (3DS) explicitly
                    r'\d{2}[A-Z]{3}\d{8}-[PMS]2[AS][SD]',     # 2AS, 2DS — pre-Legion
                    r'\d{2}[A-Z]{3}\d{8}-MNBS',
                    r'\d{2}[A-Z]{3}\d{8}-PNBS',
                    r'\d{2}[A-Z]{3}\d{8}-S\d?DS',             # stereo
                ],
        },
        'metadata_finder': {
            'type':         'sibling_strip_tile',
            'pattern':      '{base_no_tile}.XML',
            'tile_pattern': r'_R\d+C\d+',
            'fallback_glob':'*.XML',
        },
        'metadata_format': 'xml',
        'fields': {
            'sensor_id_raw': {'tag': 'SATID',  'fallback_tags': ['satId', 'platformName']},
            'catid':         {'tag': 'CATID',  'fallback_tags': ['catalogId', 'imageId']},
            'product_level': {'tag': 'PRODUCT_LEVEL'},
        },
        'geometry_source': {'type': 'raster_bounds'},
        'sensor_lookup': {
            'WV01': 'WorldView-1', 'WV02': 'WorldView-2',
            'WV03': 'WorldView-3', 'WV04': 'WorldView-4',
            'GE01': 'GeoEye-1',
            'QB02': 'QuickBird',
        },
        'sensor_default': 'Maxar',
        'image_type_from_filename': {
            r'-P\d?[AS][AS]':  'P',     # P2AS, P3AS, etc.
            r'-M\d?[AS][AS]':  'MS',    # M2AS, M3AS, etc.
            r'-S\d?DS':        'MS',    # stereo bundles often MS
            r'-MNBS':          'MS',    # mosaic basic
            r'-PNBS':          'P',
        },
        'constellation_from_sensor': {
            r'^WV': 'WorldView',
            r'^GE': 'GeoEye',
            r'^QB': 'QuickBird',
        },
    },

    # ----- Pixxel: prebuilt footprint (preferred — fast) -----
    'pixxel_fpt': {
        'acquisition_id_field': 'catid',
        'affiliation': 'Pixxel',
        'constellation': 'Firefly',
        'detect': {
            'filename_patterns': [r'^FF0\d_.*_FPT\.geojson$'],
        },
        'metadata_finder': {
            # The geojson IS the metadata + geometry source
            'type': 'self',
        },
        'metadata_format': 'json',
        'fields': {
            # Pixxel FPT geojsons typically have these in `properties`:  .. actually this is incorrect (V3)
            'sensor_id_raw':    'properties.satellite_id',
            #'catid':             ,
            'acquired':          'properties.acquired',
            'cloud_percent':     'properties.cloud_percent',
            'product_level':     'properties.processing_level',
            'gsd':               'properties.gsd',

        },
        'geometry_source': {
            'type': 'inline_geojson',
            'path': 'geometry',
            'crs':  'EPSG:4326',
        },
        'sensor_lookup_regex': r'FF0?([1-6])',
        'sensor_format':       'FF0{n}',
        'sensor_default':      'Pixxel',
        'image_type':          'HYPER',
    },

    # ----- Pixxel: raster with XML sidecar (fallback) -----
    'pixxel': {
        'acquisition_id_field': 'sensor_image_id',          # ← changed from 'catid'
        'affiliation': 'Pixxel',
        'constellation': 'Firefly',
        'detect': {
            'filename_patterns': [r'^FF0\d_.*\.tif$']
        },
        'metadata_finder': {'type': 'sibling', 'pattern': '{base}.xml'},
        'metadata_format': 'xml',
        'fields': {
            'sensor_id_raw':  {'tag': 'Satellite'},
            # 'image_id':       {'tag': 'Image_ID'},               # ← from XML when available
            # 'catid':          {'tag': 'Image_ID', 'fallback_tags': ['Order_Id']},
            # 'product_level':  {'tag': 'Processing_Level'},
            'sun_elevation':    {'tag': 'Sun_Elevation_Angle'},
            'sun_azimuth':      {'tag': 'Sun_Azimuth_Angle'},
            #'satellite_azimuth':      {'tag': '?'},   # NOTE! Pixxel seems to be missing the Satellite Azimuth or Incidence Angle - can be calc'd using Off_Nadir_Angle and Altitude
            'view_angle':       {'tag': 'Off_Nadir_Angle'},
        },
        'extract_from_filename': {
            'image_id':         r'FF0\d_\d{8}_\d+_(\d+)_[LP]',
            'sensor_image_id':  r'(FF0\d_\d{8}_\d+_\d+)_[LP]',   # sensor + date + order + id
             'sensor_id_raw': r'^(FF0\d)_',                   # ← add this
        },
        'geometry_source': {'type': 'raster_bounds'},
        'sensor_lookup_regex': r'FF0?([1-6])',
        'sensor_format':       'FF0{n}',
        'sensor_default':      'Pixxel',
        'image_type':          'HYPER',
    },

    # ----- Airbus DIMAP family (Pleiades, Pleiades Neo, SPOT) -----
    'airbus_dimap': {
        'acquisition_id_field': 'catid', # 'DATASET_NAME',#'catid',
        'affiliation': 'Airbus',
        'detect': {
                    'filename_patterns': [
            r'^DIM_',
            r'^IMG_PHR',
            r'^IMG_SPOT',
            r'^IMG_PNEON',           # catches STD, HD, STE
            r'^IMG_PNEO',           
            r'_PHR1[AB]_',
            r'_SPOT[67]_',
            r'^PNEO\d',
            ],
        },
        'metadata_finder': {
            'type':         'sibling',
            'pattern':      'DIM_{base_dim}.XML',
            'fallback_glob':'DIM_*.XML',
        },
        'metadata_format': 'xml',
        'fields': {
            'acquisition_datetime': {'tag': 'START'} ,
            'mission':       {'tag': 'MISSION', 'fallback_tags': ['INSTRUMENT']},
            'mission_index': {'tag': 'MISSION_INDEX'},
            'catid':         {'tag': 'SOURCE_ID','fallback_tags': ['DATASET_NAME']},
            'num_bands':     {'tag': 'NBANDS', 'cast': 'int'},
            'product_level': {'tag': 'PROCESSING_LEVEL', 'fallback_tags': ['PRODUCT_TYPE']},
            'radiometric_type': {'tag': 'RADIOMETRIC_PROCESSING'},
            'cloud_percent': {'tag': 'CLOUD_COVERAGE'},
            'gsd':             {'tag': 'GSD_ACROSS_TRACK'},
            'sun_elevation':       {'tag': 'SUN_ELEVATION', 'cast': 'int'},
            'sun_azimuth':         {'tag': 'SUN_AZIMUTH', 'cast': 'int'},
            'satellite_azimuth':   {'tag': 'AZIMUTH_ANGLE', 'cast': 'int'},
            'satellite_elevation': {'tag': 'INCIDENCE_ANGLE', 'cast': 'int'},
            'view_angle':          {'tag': 'VIEWING_ANGLE_ACROSS_TRACK', 'cast': 'int'},
        },
        'geometry_source': {'type': 'raster_bounds'},
        'constellation_from_mission': {
            r'^PNEO':                'Pleiades Neo',
            r'^PHR|^PLEIADES':       'Pleiades',
            r'^SPOT':                'SPOT',
        },
        # Build sensor name by combining MISSION and MISSION_INDEX
        'sensor_combine_mission_and_index': {
            'PHR':  'PHR{idx}',     # PHR + 1B → PHR1B
            'SPOT': 'SPOT{idx}',    # SPOT + 6 → SPOT6
            'PNEO': 'PNEO{idx}',    # PNEO + 3 → PNEO3
        },
    },

    # ----- Satellogic (STAC GeoJSON) -----
    'satellogic': {
        'acquisition_id_field': 'image_id',
        'affiliation': 'Satellogic',
        'constellation': 'Aleph-1',
        'detect': {
            'filename_patterns': [r'_SN\d+_', r'NEWSAT'],
            'metadata_glob':     '*_metadata_stac.geojson',
        },
        'metadata_finder': {
            'type':    'sibling',
            'pattern': '{base_clean}_metadata_stac.geojson',
            'fallback_glob': '*.geojson',
        },
        'metadata_format': 'json',
        'fields': {
            'image_id':       'id',                                # ← add this (top-level)
            'sensor_id_raw':  'properties.satl:sat_id',
            'gsd':            'properties.gsd',
            'product_level':  'properties.satl:product_name',
            'product_version':  'properties.satl:product_version',
            'acquired':            'properties.datetime',
            'cloud_percent':       'properties.eo:cloud_cover',
            'sun_elevation':       'properties.view:sun_elevation',
            'sun_azimuth':         'properties.view:sun_azimuth',
            'satellite_azimuth':   'properties.view:azimuth',
            'satellite_elevation': 'properties.view:incidence_angle',
            'view_angle':          'properties.view:off_nadir',
        },
        'geometry_source': {'type': 'inline_geojson', 'path': 'geometry', 'crs': 'EPSG:4326'},
        'sensor_lookup_regex': r'NEWSAT(\d+)',
        'sensor_format':       'SN{n:02d}',
        'sensor_default':      'Satellogic',
        'image_type':          'MS',
    },
}
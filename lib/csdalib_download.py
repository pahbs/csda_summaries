# CSDA Downloading
from concurrent.futures import ThreadPoolExecutor, as_completed

def _process_one_item(item, client, download_dir=None):
    info = get_product_info_smart(item, client, download_dir)
    info['item_id'] = item.id
    return info

def download_all_assets(item, client, output_dir, skip=None, overwrite=True):
    """
    Download every asset of a STAC item to a directory.
    overwrite=False keeps files already on disk (non-empty), so a re-run resumes.
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
        if not overwrite and local_path.exists() and local_path.stat().st_size > 0:
            downloaded[key] = local_path
            continue

        try:
            client.download_item(item, key, str(local_path))
            downloaded[key] = local_path
            print(f'  ✓ {key:20s}  → {filename}')
        except Exception as e:
            print(f'  ✗ {key:20s}  {e}')
    
    return downloaded


import re
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile


PRODUCT_INFO_PROFILES = {
    # Which STAC collection or platform this profile matches
    # For each: what to look for in the XML

    'airbus_dimap': {
        'match_platform':      lambda p: any(x in str(p).upper() for x in
                                             ('SPOT', 'PLEIADES', 'PHR', 'PNEO')),
        'metadata_asset_keys': ['metadata', 'dimap', 'xml', 'dim'],
        'metadata_filename_pattern': r'^DIM_.*\.XML$',
        'xml_tags': {
            'product_type':            ['PROCESSING_LEVEL', 'PROCESSING_LEVEL_DESC'],
            'radiometric_processing':  ['RADIOMETRIC_PROCESSING'],
            'spectral_processing':     ['SPECTRAL_PROCESSING'],
            'product_name':            ['DATASET_NAME', 'JOB_ID'],
            'mission':                 ['MISSION_INDEX', 'MISSION'],
            'satellite':               ['MISSION', 'INSTRUMENT'],   # ← add for consistency
        },
    },

    'maxar': {
        'match_platform':      lambda p: any(x in str(p).upper() for x in
                                             ('WORLDVIEW', 'GEOEYE', 'QUICKBIRD',
                                              'LEGION', 'WV0', 'GE0', 'LG0')),
        'metadata_asset_keys': ['imd', 'IMD', 'metadata', 'xml'],  # ← IMD first
        'metadata_filename_pattern': r'.*\.(IMD|XML)$',            # accept either
        'metadata_format':   'imd',                                # tell parser IMD is preferred
        'xml_tags': {
            'product_type':      ['PRODUCT_TYPE', 'productType'],
            'product_level':     ['PRODUCT_LEVEL', 'productLevel'],
            'catalog_id':        ['CATID', 'catalogId'],
            'satid':             ['SATID', 'satelliteId'],
            'num_bands':         ['NUMBANDS', 'numBands'],
        },
    },

    'pixxel': {
        'match_platform':      lambda p: 'PIXXEL' in str(p).upper() or 'FIREFLY' in str(p).upper(),
        'metadata_asset_keys': ['metadata', 'xml'],
        'metadata_filename_pattern': r'.*_L[12][ABC]\.xml$',
        'xml_tags': {
            'product_type':      ['Processing_Level', 'Output_Quantity'],
            'satellite':         ['Satellite'],
            'image_id':          ['Image_ID'],
            'atmospheric_model': ['Atmospheric_Model'],
        },
    },

    'planet': {
        'match_platform':      lambda p: any(x in str(p).upper() for x in
                                             ('PLANET', 'PLANETSCOPE', 'SKYSAT', 'TANAGER')),
        'metadata_asset_keys': ['metadata', 'metadata_json'],
        'metadata_filename_pattern': r'.*\.json$',
        # Planet uses JSON, not XML — the function branches on this
        'metadata_format':   'json',
        'json_paths': {
            'product_type':    'properties.item_type',
            'product_level':   'properties.publishing_stage',
            'quality':         'properties.quality_category',
            'sensor':          'properties.satellite_id',
        },
    },

    'satellogic': {
        'match_platform':      lambda p: any(x in str(p).upper() for x in ('SATELLOGIC', 'ALEPH', 'NEWSAT')),

        #'metadata_asset_keys': ['metadata', 'stac', 'geojson'],
        'metadata_filename_pattern': r'.*_metadata_stac\.geojson$',
        'metadata_asset_keys': ['geojson-metadata', 'xml-metadata'],
        'metadata_format':     'json',
        'json_paths': {
            'satellite':              'properties.satl:sat_id',
            'product_level':          'properties.satl:product_name',
            'product_type':           'properties.satl:product_name',
            'radiometric_processing': 'properties.satl:outcome',
            'spectral_processing':    'properties.instruments',   # 'multispectral' or 'panchromatic'
            'gsd':                    'properties.gsd',
            'acquisition_datetime':   'properties.datetime',
        },
        },
}




def detect_profile(item):
    """Determine which product-info profile applies to a STAC item."""
    platform = item.properties.get('platform', '')
    instruments = ','.join(item.properties.get('instruments', []))
    hint = f'{platform} {instruments}'
    
    for name, profile in PRODUCT_INFO_PROFILES.items():
        if profile['match_platform'](hint):
            return name, profile
    return None, None

def get_metadata_asset(item, profile):
    """Find the metadata asset for an item, using profile hints in priority order."""
    hints = profile.get('metadata_asset_keys', [])
    
    # Try each hint in order — return the first asset whose key contains this hint
    for hint in hints:
        for key, asset in item.assets.items():
            if hint.lower() in key.lower():
                return key, asset
    
    # Fallback: filename pattern
    pattern = profile.get('metadata_filename_pattern')
    if pattern:
        for key, asset in item.assets.items():
            filename = asset.href.split('/')[-1]
            if re.match(pattern, filename, re.IGNORECASE):
                return key, asset
    
    return None, None

def parse_xml_with_tags(xml_content, tag_specs):
    """Parse XML and extract values for specified tags (with fallbacks)."""
    root = ET.fromstring(xml_content)
    
    # Strip namespaces to simplify tag matching
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
    
    extracted = {}
    for std_name, tag_list in tag_specs.items():
        value = None
        for tag in tag_list:
            elem = root.find(f'.//{tag}')
            if elem is not None and elem.text:
                value = elem.text.strip()
                break
        extracted[std_name] = value
    return extracted

def parse_json_with_paths(json_content, json_paths):
    # print(f'DEBUG: type={type(json_content)}, len={len(json_content) if hasattr(json_content, "__len__") else "?"}')
    # print(f'DEBUG: first 50 chars: {json_content[:50]!r}')
    import json
    doc = json.loads(json_content) if isinstance(json_content, (str, bytes)) else json_content
    
    def get_nested(d, path):
        for key in path.split('.'):
            if isinstance(d, dict) and key in d:
                d = d[key]
            else:
                return None
        return d
    
    return {name: get_nested(doc, path) for name, path in json_paths.items()}

def _fetch_asset_content(asset, client):
    """Download the content of a STAC asset."""
    import urllib.request
    href = asset.href
    
    # If the client can download it directly, use that
    if client is not None and hasattr(client, 'download_item'):
        try:
            with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tmp:
                # Adjust to your CsdaClient's API
                client.download_asset(asset, tmp.name)
                with open(tmp.name, 'rb') as f:
                    return f.read()
        except Exception:
            pass  # Fall through to direct download
    
    # Direct HTTPS download
    if href.startswith('http'):
        with urllib.request.urlopen(href) as response:
            return response.read()
    
    # Local file
    if href.startswith('file://'):
        with open(href[7:], 'rb') as f:
            return f.read()
    
    with open(href, 'rb') as f:
        return f.read()

import tempfile
from pathlib import Path

def get_product_info_smart(item, client, download_dir=None):
    """
    Discover product info by downloading only the metadata asset (not imagery).
    IMD/XML files are tiny (~KB) so this is very fast.
    """
    profile_name, profile = detect_profile(item)
    if profile is None:
        return {'vendor_profile': 'unknown', 'note': 'No profile match'}
    
    # Find the metadata-only asset
    asset_key, asset = get_metadata_asset(item, profile)
    if asset is None:
        return {'vendor_profile': profile_name, 'note': 'No metadata asset'}
    
    # Download JUST the metadata file to a temp location
    if download_dir:
        local_path = Path(download_dir) / f'{item.id}_{asset_key}'
    else:
        # Auto-cleanup temp file
        tmp = tempfile.NamedTemporaryFile(suffix='.meta', delete=False)
        local_path = Path(tmp.name)
        tmp.close()
    
    try:
        client.download_item(item, asset_key, str(local_path))
        
        with open(local_path, 'rb') as f:
            content = f.read()

        #print(f'DEBUG content type: {type(content)}, len={len(content)}, head={content[:60]!r}')
        
        # Parse based on format
        if profile.get('metadata_format') == 'imd':
            parsed = extract_maxar_product_info(content)
        elif profile.get('metadata_format') == 'json':
            parsed = parse_json_with_paths(content, profile['json_paths'])
        else:
            parsed = parse_xml_with_tags(content, profile['xml_tags'])
        
        result = {'vendor_profile': profile_name,
                  'metadata_asset_key': asset_key,
                  **parsed}
    except Exception as e:
        result = {'vendor_profile': profile_name, 'error': str(e)}
    finally:
        # Clean up temp file if we created one
        if not download_dir and local_path.exists():
            local_path.unlink()

    result = normalize_airbus_satellite(result)
    return result

def parse_imd_file(content):
    """Parse a Maxar IMD text file into a nested dict."""
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='replace')

    result = {}
    stack = []
    current = result

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('/*') or line.startswith('//'):
            continue

        # Group start:  BEGIN_GROUP = IMAGE_1
        if line.startswith('BEGIN_GROUP'):
            group_name = line.split('=', 1)[1].strip().rstrip(';').strip()
            new_group = {}
            current[group_name] = new_group
            stack.append(current)
            current = new_group

        # Group end:  END_GROUP = IMAGE_1
        elif line.startswith('END_GROUP'):
            if stack:
                current = stack.pop()

        # Key-value:  key = "value";  or  key = 42;
        elif '=' in line:
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip().rstrip(';').strip().strip('"')
            # Try numeric conversion
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
            current[key] = val

        # End of file marker
        elif line in ('END;', 'END'):
            break

    return result

def extract_maxar_product_info(content):
    parsed = parse_imd_file(content)
    image_key = next((k for k in parsed if k.startswith('IMAGE')), None)
    img = parsed.get(image_key, {}) if image_key else {}

    return {
        # Standard cross-vendor names
        'product_type':           parsed.get('productType'),
        'product_level':          parsed.get('productLevel'),
        'radiometric_processing': parsed.get('radiometricLevel'),
        'spectral_processing':    parsed.get('bandId'),
        'satellite':              img.get('satId'),
        # Additional Maxar-specific fields
        'catalog_id':             img.get('CatId'),
        'product_order_id':       parsed.get('productOrderId'),
        'radiometric_enhancement':parsed.get('radiometricEnhancement'),
        'scan_direction':         img.get('scanDirection'),
        'sun_elevation':          img.get('meanSunEl'),
        'off_nadir_view_angle':   img.get('meanOffNadirViewAngle'),
        'cloud_cover':            img.get('cloudCover'),
    }

def normalize_airbus_satellite(info):
    """Combine Airbus's MISSION + MISSION_INDEX into a satellite name."""
    if info.get('vendor_profile') != 'airbus_dimap':
        return info
    mission = info.get('mission', '')
    satellite = info.get('satellite', '')
    if satellite and mission:
        # e.g., "PHR" + "1A" → "PHR1A", "SPOT" + "6" → "SPOT6"
        info['satellite'] = f'{satellite}{mission}'
    return info

def plot_image(local_path, stac_gdf, sites_gdf, item_id,
               rgb_indices=[0, 1, 2], max_dim=1024, ax=None):

    import matplotlib.pyplot as plt
    import rasterio
    from rasterio.plot import show
    from rasterio.warp import transform_bounds, calculate_default_transform, reproject, Resampling
    import contextily as ctx
    import numpy as np
    from matplotlib.ticker import MaxNLocator
    from pyproj import Transformer
    from matplotlib.offsetbox import AnchoredText
    from matplotlib_scalebar.scalebar import ScaleBar
    from shapely.geometry import box
    import os

    print(f'Plotting: {local_path}')
    
    # Filter STAC entry safely without overwriting the parent dataframe variable
    item_gdf = stac_gdf[stac_gdf.id == item_id].iloc[0:1]
    
    if len(item_gdf) == 0:
        print(f"⚠️ Warning: {item_id} not found in stac_gdf")
        return

    collection = item_gdf.collection.iloc[0] if 'collection' in item_gdf.columns else 'Unknown Collection'
    date_str = item_gdf.datetime.iloc[0] if 'datetime' in item_gdf.columns else ''

    try:
        with rasterio.open(local_path) as dataset:
            # 1. Calculate downsampled target dimensions
            h, w = dataset.height, dataset.width
            if max(h, w) > max_dim:
                scale = max_dim / float(max(h, w))
                out_h, out_w = int(h * scale), int(w * scale)
            else:
                out_h, out_w = h, w

            # 2. Read ONLY the downsampled array into memory
            data = dataset.read(
                out_shape=(dataset.count, out_h, out_w),
                resampling=Resampling.bilinear
            )

            # Calculate scaled source transform for the downsampled array
            src_transform = dataset.transform * dataset.transform.scale(
                (w / out_w),
                (h / out_h)
            )

            nodata = dataset.nodata
            dst_crs = 'EPSG:3857'

            # 3. Compute destination transform and dimensions for Web Mercator (EPSG:3857)
            dst_transform, dst_width, dst_height = calculate_default_transform(
                dataset.crs, dst_crs, out_w, out_h, *dataset.bounds
            )

            left, bottom, right, top = transform_bounds(
                dataset.crs, dst_crs, *dataset.bounds
            )

            # 4. Fast Reprojection of downsampled bands
            reprojected = np.zeros((dataset.count, dst_height, dst_width), dtype=data.dtype)
            for i in range(dataset.count):
                reproject(
                    source=data[i],
                    destination=reprojected[i],
                    src_transform=src_transform,
                    src_crs=dataset.crs,
                    dst_transform=dst_transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )

            # 5. Mask nodata values
            if nodata is not None:
                mask_reproj = np.any(reprojected == nodata, axis=0)
            else:
                mask_reproj = np.all(reprojected == 0, axis=0)

            # Create figure/ax only if ax wasn't passed in
            standalone_plot = False
            if ax is None:
                fig, ax = plt.subplots(figsize=(14, 10))
                standalone_plot = True

            ax.set_xlim(left, right)
            ax.set_ylim(bottom, top)

            # Add Basemap
            ctx.add_basemap(ax, source=ctx.providers.Esri.WorldGrayCanvas,
                            crs=dst_crs, attribution=' ')

            # Safe RGB selection (fallback if requested bands exceed available count)
            valid_rgb = [idx for idx in rgb_indices if idx < dataset.count]
            if len(valid_rgb) < 3:
                valid_rgb = list(range(min(3, dataset.count)))

            img_rgb = np.moveaxis(reprojected[valid_rgb], 0, -1)

            # 6. Contrast Stretch (2nd to 98th percentile)
            img_stretched = np.zeros_like(img_rgb, dtype=np.uint8)
            for i in range(img_rgb.shape[-1]):
                band = img_rgb[..., i].astype(np.float32)
                valid = band[~mask_reproj]
                if len(valid) > 0:
                    p2, p98 = np.percentile(valid, [2, 98])
                else:
                    p2, p98 = band.min(), band.max()
                stretched = np.clip((band - p2) / (p98 - p2 + 1e-10), 0, 1) * 255
                img_stretched[..., i] = stretched.astype(np.uint8)

            alpha = (~mask_reproj * 255).astype(np.uint8)
            
            # Tile RGBA channels
            if img_stretched.shape[-1] == 3:
                rgba = np.dstack([img_stretched, alpha])
            else:
                rgba = img_stretched

            ax.imshow(rgba, extent=(left, right, bottom, top), zorder=2)

            # 7. Plot STAC Footprint
            item_gdf.to_crs(3857).plot(
                ax=ax,
                facecolor='none',
                edgecolor='black',
                linestyle='--',
                linewidth=2.5,
                zorder=3,
            )

            # 8. Plot Intersecting Sites
            raster_footprint_3857 = box(left, bottom, right, top)
            sites_3857 = sites_gdf.to_crs('EPSG:3857')
            intersecting_sites = sites_3857[sites_3857.intersects(raster_footprint_3857)]

            if len(intersecting_sites) > 0:
                intersecting_sites.plot(
                    ax=ax,
                    facecolor='none',
                    edgecolor='red',
                    linestyle='--',
                    linewidth=1.5,
                    zorder=3,
                )

                for _, s in intersecting_sites.iterrows():
                    c = s.geometry.centroid
                    ax.annotate(
                        str(s.get('site_name', s.get('name', 'Site'))),
                        xy=(c.x, c.y),
                        fontsize=9, color='red', weight='bold',
                        ha='center', va='center',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                  alpha=0.7, edgecolor='none'),
                        zorder=4,
                    )

            # 9. Axis ticks -> Lat/Lon
            ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))

            transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

            x_ticks = ax.get_xticks()
            mid_y = (bottom + top) / 2
            lons, _ = transformer.transform(x_ticks, [mid_y] * len(x_ticks))
            ax.set_xticklabels([f"{lon:.3f}°" for lon in lons])

            y_ticks = ax.get_yticks()
            mid_x = (left + right) / 2
            _, lats = transformer.transform([mid_x] * len(y_ticks), y_ticks)
            ax.set_yticklabels([f"{lat:.3f}°" for lat in lats])

            ax.set_xlabel('Longitude', fontsize=9, labelpad=4)
            ax.set_ylabel('Latitude', fontsize=9, labelpad=4)
            ax.tick_params(axis='both', which='major', labelsize=8)

            scalebar = ScaleBar(dx=1, units='m', location='lower right', length_fraction=0.2, box_alpha=0.7)
            ax.add_artist(scalebar)

            ax.set_title(f'{collection} | {date_str}',
                         fontsize=10, color='#333', loc='left', pad=6)

            ax.annotate(os.path.basename(local_path),
                        xy=(0.02, 0.02), xycoords='axes fraction',
                        fontsize=8, color='#555',
                        verticalalignment='bottom',
                        bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))

    except Exception as e:
        print(f"⚠️ Error rendering {local_path}: {e}")
        if ax is not None:
            ax.text(0.5, 0.5, f"Render Error\n{item_id}", ha='center', va='center', color='red', transform=ax.transAxes)

    if standalone_plot:
        plt.show()
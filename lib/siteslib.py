import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box
import numpy as np
from urllib.parse import quote


'''
Library of functions to handle processing of site AOIs
'''
def update_sites_attributes(sites_gdf, site_configs):
    """
    Update sites GeoDataFrame with attributes based on configuration.
    
    Parameters:
    -----------
    sites_gdf : GeoDataFrame
        Sites geodataframe to update
    site_configs : list of dict
        List of configurations, each with 'sites' and 'attributes' keys
        
    Returns:
    --------
    GeoDataFrame : Updated sites (copy)
    list : All site names from configs
    """
    sites_updated = sites_gdf.copy()
    all_sites = []
    
    for config in site_configs:
        site_list = config['sites']
        attributes = config['attributes']
        
        # Update attributes for these sites
        mask = sites_updated['Site Name'].isin(site_list)
        for key, value in attributes.items():
            sites_updated.loc[mask, key] = value
        
        all_sites.extend(site_list)
    
    return sites_updated, all_sites
    
def read_from_sheet(SPREADSHEET_ID = '13MrpqFtAOqQY9WdW9lHNsqjCbG-e3VQkEDbHOGIKa6k', SHEET_NAME = 'Evaluation Sites', CSDA_ONLY=True):
    # 2. Encode the sheet name for safe use in a URL
    ENCODED_SHEET_NAME = quote(SHEET_NAME)
    
    # 3. Construct the full URL using the gviz/tq endpoint
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={ENCODED_SHEET_NAME}"
    
    # 4. Use pandas to read the CSV data directly from the URL
    try:
        sites = pd.read_csv(url)
        
        if SHEET_NAME == 'Evaluation Sites':
            #sites['Site Name'] = sites['Site Name abbrev'].str.rstrip()
            # If no abbreviation set, then just use Site Name
            sites['Site Name'] = sites['Site Name abbrev'].fillna(sites['Site Name']).str.rstrip()
            if CSDA_ONLY:
                # Get only Priority Sites - used for defining CSDA sites for now
                sites = sites[sites['Program Use'] == 'CSDA']
        
    except Exception as e:
        print(f"An error occurred: {e}")
    
    # # Get only Priority Sites = high
    # sites = sites[sites['Priority Level'] == 'high']
    
    # Get the list of columns to drop
    cols_to_drop = sites.columns[sites.columns.str.contains('Unnamed')]
    sites = sites.drop(columns=cols_to_drop)

    return sites
    
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


def create_box_aoi(gdf, BOX_KM):
    """
    Create square box AOI for each site in GeoDataFrame
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        Input GeoDataFrame with point geometries
    BOX_KM : float
        Side length of box in kilometers
        
    Returns:
    --------
    GeoDataFrame with box geometries in original CRS
    """
    if gdf.crs and gdf.crs.is_geographic:
        original_crs = gdf.crs
        box_geoms = []
        
        for idx, row in gdf.iterrows():
            # Check and convert None to empty geometry
            if row.geometry is None:
                print(f"Warning: Skipping None geometry at index {idx}")
                box_geoms.append(Point())  # Append empty Point directly
                continue
                
            if row.geometry.is_empty:
                print(f"Warning: Skipping empty geometry at index {idx}")
                box_geoms.append(row.geometry)
                continue
            
            site_gdf = gpd.GeoDataFrame([row], geometry='geometry', crs=original_crs)
            
            try:
                bounds = row.geometry.bounds
                lon = (bounds[0] + bounds[2]) / 2
                lat = (bounds[1] + bounds[3]) / 2
            except Exception as e:
                print(f"Warning: Could not get bounds for index {idx}: {e}")
                box_geoms.append(Point())
                continue
            
            # Determine projection
            if abs(lat) < 5:
                proj_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
            else:
                try:
                    proj_crs = site_gdf.estimate_utm_crs()
                except Exception as e:
                    proj_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
            
            try:
                site_projected = site_gdf.to_crs(proj_crs)
                x, y = site_projected.geometry.iloc[0].x, site_projected.geometry.iloc[0].y
                
                half_size = (BOX_KM * 1000) / 2
                box_geom = box(x - half_size, y - half_size, x + half_size, y + half_size)
                
                box_gdf = gpd.GeoDataFrame([{'geometry': box_geom}], 
                                           geometry='geometry', 
                                           crs=proj_crs)
                box_original = box_gdf.to_crs(original_crs).geometry.iloc[0]
                
                box_geoms.append(box_original)
            except Exception as e:
                print(f"Warning: Could not create box for index {idx}: {e}")
                box_geoms.append(Point())
                continue
        
        gdf_boxes = gdf.copy()
        gdf_boxes['geometry'] = box_geoms
        
        return gdf_boxes
    else:
        # Already in projected CRS
        gdf_boxes = gdf.copy()
        box_geoms = []
        for idx, row in gdf.iterrows():
            if row.geometry is None:
                box_geoms.append(Point())
                continue
                
            if row.geometry.is_empty:
                box_geoms.append(row.geometry)
                continue
                
            x, y = row.geometry.x, row.geometry.y
            half_size = (BOX_KM * 1000) / 2
            box_geom = box(x - half_size, y - half_size, x + half_size, y + half_size)
            box_geoms.append(box_geom)
        gdf_boxes['geometry'] = box_geoms
        return gdf_boxes

def create_sites_gdf_with_aois(sites_df, default_size_km=3, 
                               custom_geojson_dict=None, 
                               multi_site_geojson_dict=None,
                               site_column='site_name', lat_column='lat', lon_column='lon'):
    
    print(f'Creating sites GeoDataFrame with mixed AOI types (circles, boxes, custom single, custom multi) ...')
    print(f'\t{sites_df.shape[0]} sites')
    print(f'\tUsing {default_size_km} km default size')
    
    """
    Parameters
    ----------
    sites_df : DataFrame
        Sites table with site name, lat/lon, and optional aoi_shape, aoi_size_km columns.
    default_size_km : float
        Default circle radius / box half-width in km when aoi_size_km is missing.
    custom_geojson_dict : dict, optional
        Mapping of {site_name: geojson_path} where each file contains a single AOI
        for that one site. Existing behavior.
    multi_site_geojson_dict : dict, optional
        Mapping for files containing multiple AOIs. Two formats supported:
    
          # Format A: file has a name field — match each AOI to a Site Name
          {'/path/file.geojson': {'name_field': 'plot_id'}}
    
          # Format B: file has no name field — supply names in order
          {'/path/file.geojson': {'site_names': ['Site1', 'Site2', 'Site3']}}
    
        Either format adds rows to the output GeoDataFrame. New rows inherit
        non-geometry attributes from sites_df rows where Site Name matches;
        sites with no match in sites_df are added with NaN attributes.
    site_column, lat_column, lon_column : str
        Column names in sites_df.
    """
    
    if custom_geojson_dict is None:
        custom_geojson_dict = {}
    if multi_site_geojson_dict is None:
        multi_site_geojson_dict = {}
    
    # ---- 1. Build initial GeoDataFrame from points ----
    geometries = []
    for lon, lat, site_name in zip(sites_df[lon_column],
                                    sites_df[lat_column],
                                    sites_df[site_column]):
        if pd.isna(lon) or pd.isna(lat):
            print(f"Warning: Missing lat/lon for {site_name} — empty Point")
            geometries.append(Point())
        else:
            geometries.append(Point(lon, lat))
    
    sites_gdf = gpd.GeoDataFrame(sites_df.copy(),
                                  geometry=geometries, crs='EPSG:4326')
    
    # ---- 2. Categorize sites by AOI type ----
    sites_with_custom = []
    sites_for_circle  = []
    sites_for_box     = []
    
    for idx, row in sites_gdf.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            print(f"Warning: skipping {row[site_column]} (invalid geometry)")
            continue
        site_name = row[site_column]
        aoi_type  = row.get('aoi_shape', 'circle')
    
        if aoi_type == 'custom' or site_name in custom_geojson_dict:
            sites_with_custom.append(idx)
        elif aoi_type == 'box':
            sites_for_box.append(idx)
        else:
            sites_for_circle.append(idx)
    
    # ---- 3. Process circles ----
    for idx in sites_for_circle:
        row = sites_gdf.loc[idx]
        size_km = row.get('aoi_size_km', default_size_km)
        if pd.isna(size_km):
            size_km = default_size_km
        subset = gpd.GeoDataFrame([row], geometry='geometry', crs='EPSG:4326')
        sites_gdf.loc[idx, 'geometry'] = buffer_site_gdf(subset, size_km).geometry.iloc[0]
    
    # ---- 4. Process boxes ----
    for idx in sites_for_box:
        row = sites_gdf.loc[idx]
        size_km = row.get('aoi_size_km', default_size_km)
        if pd.isna(size_km):
            size_km = default_size_km
        subset = gpd.GeoDataFrame([row], geometry='geometry', crs='EPSG:4326')
        sites_gdf.loc[idx, 'geometry'] = create_box_aoi(subset, size_km).geometry.iloc[0]
    
    # ---- 5. Process single-site custom geojson (existing behavior) ----
    for idx in sites_with_custom:
        site_name = sites_gdf.loc[idx, site_column]
        if site_name not in custom_geojson_dict:
            continue
        geojson_path = custom_geojson_dict[site_name]
        try:
            custom_gdf = gpd.read_file(geojson_path)
            if custom_gdf.crs != sites_gdf.crs:
                custom_gdf = custom_gdf.to_crs(sites_gdf.crs)
            custom_geom = (custom_gdf.unary_union if len(custom_gdf) > 1
                           else custom_gdf.geometry.iloc[0])
            sites_gdf.loc[idx, 'geometry'] = custom_geom
            print(f"\t✓ Loaded single-site custom geometry for {site_name}")
        except Exception as e:
            print(f"ERROR loading custom geometry for {site_name}: {e}")
            print('  Falling back to default circle buffer.')
            subset = gpd.GeoDataFrame([sites_gdf.loc[idx]],
                                       geometry='geometry', crs='EPSG:4326')
            sites_gdf.loc[idx, 'geometry'] = buffer_site_gdf(
                subset, default_size_km).geometry.iloc[0]
    
    # # ---- 6. Process multi-site custom geojson (NEW) ----
    # new_rows = []
    # for path, spec in multi_site_geojson_dict.items():
    #     try:
    #         custom_gdf = gpd.read_file(path)
    #         if custom_gdf.crs != sites_gdf.crs:
    #             custom_gdf = custom_gdf.to_crs(sites_gdf.crs)
    #     except Exception as e:
    #         print(f"ERROR reading multi-site file {path}: {e}")
    #         continue
    
    #     # Extract site names per feature
    #     if 'name_field' in spec:
    #         field = spec['name_field']
    #         if field not in custom_gdf.columns:
    #             print(f"ERROR: name_field '{field}' not found in {path}; skipping.")
    #             continue
    #         names = custom_gdf[field].astype(str).tolist()
    #     elif 'site_names' in spec:
    #         names = list(spec['site_names'])
    #         if len(names) != len(custom_gdf):
    #             print(f"ERROR: site_names length ({len(names)}) != features in "
    #                   f"{path} ({len(custom_gdf)}); skipping.")
    #             continue
    #     else:
    #         print(f"ERROR: spec for {path} must contain 'name_field' or 'site_names'; "
    #               'skipping.')
    #         continue
    
    #     for feat_idx, name in enumerate(names):
    #         geom = custom_gdf.geometry.iloc[feat_idx]
    
    #         # Try to inherit attributes from existing sites_df row
    #         existing = sites_gdf[sites_gdf[site_column] == name]
    #         if len(existing):
    #             # Update geometry of the matched row in place
    #             match_idx = existing.index[0]
    #             sites_gdf.loc[match_idx, 'geometry'] = geom
    #             print(f"\t✓ Multi-site: replaced geometry for existing '{name}'")
    #         else:
    #             # Build a new row with NaN attributes except site name + geometry
    #             new_row = {col: pd.NA for col in sites_gdf.columns
    #                        if col != 'geometry'}
    #             new_row[site_column] = name
    #             new_row['geometry']  = geom
    #             new_rows.append(new_row)
    #             print(f"\t+ Multi-site: added new entry '{name}'")
    # ---- 6. Process multi-site custom geojson (preserves attributes) ----
    new_rows = []
    for path, spec in multi_site_geojson_dict.items():
        try:
            custom_gdf = gpd.read_file(path)
            if custom_gdf.crs != sites_gdf.crs:
                custom_gdf = custom_gdf.to_crs(sites_gdf.crs)
        except Exception as e:
            print(f"ERROR reading multi-site file {path}: {e}")
            continue
        
        # Get site names per feature
        if 'name_field' in spec:
            field = spec['name_field']
            if field not in custom_gdf.columns:
                print(f"ERROR: name_field '{field}' not found in {path}; skipping.")
                continue
            names = custom_gdf[field].astype(str).tolist()
        elif 'site_names' in spec:
            names = list(spec['site_names'])
            if len(names) != len(custom_gdf):
                print(f"ERROR: site_names length ({len(names)}) != features in "
                      f"{path} ({len(custom_gdf)}); skipping.")
                continue
        else:
            print(f"ERROR: spec for {path} must contain 'name_field' or 'site_names'; "
                  'skipping.')
            continue
        
        for feat_idx, name in enumerate(names):
            geom = custom_gdf.geometry.iloc[feat_idx]
        
            # Look up attributes from sites_df
            existing = sites_gdf[sites_gdf[site_column] == name]
        
            if len(existing):
                # ---- Site exists in sites_df → replace its geometry, keep attributes ----
                match_idx = existing.index[0]
                sites_gdf.loc[match_idx, 'geometry'] = geom
                print(f"\t✓ Multi-site: replaced geometry for '{name}' "
                      f"\t(attributes preserved)")
            else:
                # ---- Site NOT in sites_df → keep original sites_df attributes from
                #      the GeoJSON itself if any matching columns exist; else NaN ----
                # Build a row matching sites_gdf's schema
                new_row = {col: pd.NA for col in sites_gdf.columns
                           if col != 'geometry'}
        
                # Pull any matching columns from the GeoJSON's own attributes
                feat_attrs = custom_gdf.iloc[feat_idx].to_dict()
                feat_attrs.pop('geometry', None)
                for col, val in feat_attrs.items():
                    if col in sites_gdf.columns:
                        new_row[col] = val
        
                new_row[site_column] = name
                new_row['geometry']  = geom
                new_rows.append(new_row)
                print(f"\t+ Multi-site: added new entry '{name}' "
                      f"\t(no match in sites_df — using GeoJSON attributes if available)")
    
    if new_rows:
        new_gdf = gpd.GeoDataFrame(new_rows,
                                    geometry='geometry',
                                    crs=sites_gdf.crs)
        sites_gdf = pd.concat([sites_gdf, new_gdf], ignore_index=True)
        sites_gdf = gpd.GeoDataFrame(sites_gdf,
                                      geometry='geometry',
                                      crs='EPSG:4326')
    
    # ---- 7. Drop empty geometries ----
    sites_gdf = sites_gdf[~sites_gdf.geometry.is_empty]
    print(f'\n\t{sites_gdf.shape[0]} sites now in geodataframe.')
    return sites_gdf

def get_multi_site_centroids(multi_site_geojson_dict):
    """
    Extract centroid lat/lon for each feature in multi-site GeoJSON files.
    Returns a DataFrame ready to copy-paste into the Eval Sites DB.
    """
    rows = []

    for path, spec in multi_site_geojson_dict.items():
        gdf = gpd.read_file(path)
        if gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')

        # Get site names per feature
        if 'name_field' in spec:
            names = gdf[spec['name_field']].astype(str).tolist()
        elif 'site_names' in spec:
            names = list(spec['site_names'])
        else:
            print(f"Skipping {path}: spec must contain 'name_field' or 'site_names'")
            continue

        # Compute centroids in equal-area projection for accuracy, then back to WGS84
        centroids = (gdf.to_crs('+proj=cea').centroid
                       .to_crs('EPSG:4326'))

        for name, c in zip(names, centroids):
            rows.append({
                'Site Name': name,
                'Longitude': round(c.x, 6),
                'Latitude':  round(c.y, 6),
                'source_file': path.split('/')[-1],
            })

    df = pd.DataFrame(rows)
    return df

def calculate_area_km2_per_site(gdf):
    """
    Calculate area in km² for each feature in its own UTM zone
    (More accurate for global datasets)
    """
    areas = []
    
    for idx, row in gdf.iterrows():
        # Create single-feature GeoDataFrame
        single_gdf = gpd.GeoDataFrame([row], geometry='geometry', crs=gdf.crs)
        
        # Project to appropriate UTM zone for this feature
        single_proj = single_gdf.to_crs(single_gdf.estimate_utm_crs())
        
        # Calculate area in km²
        area_km2 = single_proj.area.iloc[0] / 1_000_000
        areas.append(area_km2)
    
    return areas

def create_corner_reflector_boxes(cr_df, sites_gdf, site_column='Site Name', lat_name='cr:lat',lon_name='cr:lon',
                                   add_columns=None):
    """
    Create box geometries for corner reflectors based on their size.
    Similar to how create_sites_gdf_with_aois creates boxes for sites.
    
    Parameters:
    -----------
    cr_df : DataFrame
        Corner reflector data with columns: Site Name, CR ID, Latitude (°), 
        Longitude (°), Size (m), etc.
    sites_gdf : GeoDataFrame
        Sites GeoDataFrame to pull additional attributes from
    site_column : str
        Column name containing site names (default: 'Site Name')
    add_columns : list
        List of column names to add from sites_gdf to cr_gdf
    """
    import geopandas as gpd
    from shapely.geometry import Point, box
    import pandas as pd
    
    if add_columns is None:
        add_columns = ['Remote Sensing Domain', 'Priority Level', 
                       'Evaluation Category', 'Source', 'Surface Domain',
                       'Assessment type(s)']
    
    # Create point geometries from lat/lon
    geometries = []
    for lon, lat in zip(cr_df[lon_name], cr_df[lat_name]):
        if pd.isna(lon) or pd.isna(lat):
            geometries.append(Point())
        else:
            geometries.append(Point(lon, lat))
    
    cr_gdf = gpd.GeoDataFrame(cr_df.copy(), geometry=geometries, crs='EPSG:4326')
    
    # Add columns from sites_gdf
    columns_to_add = [col for col in add_columns if col in sites_gdf.columns]
    if columns_to_add:
        site_attrs = sites_gdf[[site_column] + columns_to_add].drop_duplicates(subset=[site_column])
        cr_gdf = cr_gdf.merge(site_attrs, on=site_column, how='left')
    
    # Create boxes around each CR based on Size field
    box_geoms = []
    for idx, row in cr_gdf.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            box_geoms.append(Point())
            continue
        
        lon, lat = row.geometry.x, row.geometry.y
        box_size_m = row['cr:size_m']
        
        # Determine projection (same logic as in create_sites_gdf_with_aois)
        if abs(lat) < 5:
            proj_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        else:
            try:
                site_gdf = gpd.GeoDataFrame([{'geometry': row.geometry}], crs='EPSG:4326')
                proj_crs = site_gdf.estimate_utm_crs()
            except Exception as e:
                proj_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        
        try:
            # Project to meters
            site_gdf = gpd.GeoDataFrame([{'geometry': row.geometry}], crs='EPSG:4326')
            site_projected = site_gdf.to_crs(proj_crs)
            x, y = site_projected.geometry.iloc[0].x, site_projected.geometry.iloc[0].y
            
            # Create box (square centered on point)
            half_size = box_size_m / 2
            box_geom = box(x - half_size, y - half_size, x + half_size, y + half_size)
            
            # Convert back to EPSG:4326
            box_gdf = gpd.GeoDataFrame([{'geometry': box_geom}], 
                                       geometry='geometry', 
                                       crs=proj_crs)
            box_original = box_gdf.to_crs('EPSG:4326').geometry.iloc[0]
            
            box_geoms.append(box_original)
        except Exception as e:
            print(f"Warning: Could not create box for CR {row.get('cr:id', idx)}: {e}")
            box_geoms.append(Point())
            continue
    
    cr_gdf['geometry'] = box_geoms
    return cr_gdf

def export_hierarchical_geojson(sites_gdf, cr_gdf, output_path):
    """
    Export sites with corner reflectors as child features.
    Both have polygon geometries (site AOIs and CR boxes).
    """
    
    # Prepare sites
    sites_export = sites_gdf.copy()
    sites_export['feature_type'] = 'site'
    sites_export['parent_site'] = None  # Top-level features
    
    # Prepare CRs as child features
    cr_export = cr_gdf.copy()
    if 'parent_site_geometry' in cr_export.columns:
        cr_export = cr_export.drop(columns=['parent_site_geometry'])
    cr_export['feature_type'] = 'corner_reflector'
    cr_export['parent_site'] = cr_export['Site Name']  # Link to parent
    
    # Combine - sites first, then their children
    combined_gdf = pd.concat([sites_export, cr_export], ignore_index=True)

    # For corner reflector sites, if parent is not None, then update Site Name by concatentating the fields 'parent_site' and 'CR ID', separating with a space
    # For corner reflector sites with a parent, build a composite Site Name
    mask = combined_gdf['parent_site'].notna()
    combined_gdf.loc[mask, 'Site Name'] = (
        combined_gdf.loc[mask, 'parent_site'].astype(str)
        + ' '
        + combined_gdf.loc[mask, 'cr:id'].astype(str)
    )
    
    # Sort to group CRs under their parent sites
    combined_gdf = combined_gdf.sort_values(['parent_site', 'feature_type'], 
                                            na_position='first')
    
    combined_gdf.to_file(output_path, driver='GeoJSON')
    
    return combined_gdf
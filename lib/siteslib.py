import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box
import numpy as np

'''
Library of functions to handle processing of site AOIs
'''

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

def create_sites_gdf_with_aois(sites_df, default_size_km=3, custom_geojson_dict=None, 
                               site_column='site_name', lat_column='lat', lon_column='lon'):
    """
    Create sites GeoDataFrame with mixed AOI types (circles, boxes, and custom)
    """
    
    if custom_geojson_dict is None:
        custom_geojson_dict = {}
    
    # Create point geometries from lat/lon, handling missing values
    geometries = []
    for lon, lat, site_name in zip(sites_df[lon_column], sites_df[lat_column], sites_df[site_column]):
        if pd.isna(lon) or pd.isna(lat):
            print(f"Warning: Missing lat/lon values, creating empty Point for {site_name}")
            geometries.append(Point())
        else:
            geometries.append(Point(lon, lat))
    
    sites_gdf = gpd.GeoDataFrame(sites_df.copy(), geometry=geometries, crs='EPSG:4326')
    
    # Determine which sites need what treatment
    sites_with_custom = []
    sites_for_circle = []
    sites_for_box = []
    
    for idx, row in sites_gdf.iterrows():
        # Skip sites with empty/None geometry
        if row.geometry is None or row.geometry.is_empty:
            print(f"Warning: Skipping site at index {row[site_column]} due to invalid geometry")
            continue
            
        site_name = row[site_column]
        aoi_type = row.get('aoi_type', 'circle')
        
        if aoi_type == 'custom' or site_name in custom_geojson_dict:
            sites_with_custom.append(idx)
        elif aoi_type == 'box':
            sites_for_box.append(idx)
        else:  # circle
            sites_for_circle.append(idx)
    
    # Process circles
    if sites_for_circle:
        for idx in sites_for_circle:
            row = sites_gdf.loc[idx]
            # Handle NaN/None values in aoi_size_km
            size_km = row.get('aoi_size_km', default_size_km)
            if pd.isna(size_km):
                size_km = default_size_km
            circle_subset = gpd.GeoDataFrame([row], geometry='geometry', crs='EPSG:4326')
            buffered = buffer_site_gdf(circle_subset, size_km)
            sites_gdf.loc[idx, 'geometry'] = buffered.geometry.iloc[0]
    
    # Process boxes
    if sites_for_box:
        for idx in sites_for_box:
            row = sites_gdf.loc[idx]
            # Handle NaN/None values in aoi_size_km
            size_km = row.get('aoi_size_km', default_size_km)
            if pd.isna(size_km):
                size_km = default_size_km
            box_subset = gpd.GeoDataFrame([row], geometry='geometry', crs='EPSG:4326')
            boxed = create_box_aoi(box_subset, size_km)
            sites_gdf.loc[idx, 'geometry'] = boxed.geometry.iloc[0]
    
    # Process custom
    if sites_with_custom:
        for idx in sites_with_custom:
            site_name = sites_gdf.loc[idx, site_column]
            
            if site_name in custom_geojson_dict:
                geojson_path = custom_geojson_dict[site_name]
                
                try:
                    custom_gdf = gpd.read_file(geojson_path)
                    
                    if custom_gdf.crs != sites_gdf.crs:
                        custom_gdf = custom_gdf.to_crs(sites_gdf.crs)
                    
                    if len(custom_gdf) > 1:
                        custom_geom = custom_gdf.unary_union
                    else:
                        custom_geom = custom_gdf.geometry.iloc[0]
                    
                    sites_gdf.loc[idx, 'geometry'] = custom_geom
                    print(f"✓ Loaded custom geometry for {site_name}")
                    
                except Exception as e:
                    print(f"ERROR loading custom geometry for {site_name}: {e}")
                    print(f"  Using default circle buffer instead")
                    fallback_subset = gpd.GeoDataFrame([sites_gdf.loc[idx]], geometry='geometry', crs='EPSG:4326')
                    buffered = buffer_site_gdf(fallback_subset, default_size_km)
                    sites_gdf.loc[idx, 'geometry'] = buffered.geometry.iloc[0]

    # Remove rows with empty geometries
    sites_gdf = sites_gdf[~sites_gdf.geometry.is_empty]
    
    return sites_gdf
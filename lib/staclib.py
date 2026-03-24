import contextily as ctx
import geopandas as gpd
import numpy as np

from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
import matplotlib.pyplot as plt

import folium
import matplotlib.colors as mcolors
import branca.colormap as cm

from pystac_client import Client
from shapely.geometry import shape
from shapely.geometry import box
from datetime import datetime

def stac_items_to_gdf(items, properties_to_extract=None):
    """
    Convert STAC items to GeoDataFrame with optional property filtering
    
    Parameters:
    -----------
    items : list
        List of pystac.Item objects
    properties_to_extract : list, optional
        Specific properties to extract. If None, extracts all properties.
    """
    records = []
    
    for item in items:
        # Extract geometry
        geom = shape(item.geometry)
        
        # Base record
        record = {
            'id': item.id,
            'collection': item.collection_id,
            'datetime': item.datetime,
            'geometry': geom,
        }
        
        # Extract bbox
        if item.bbox:
            record['bbox'] = item.bbox
        
        # Extract specific or all properties
        if properties_to_extract:
            for prop in properties_to_extract:
                record[prop] = item.properties.get(prop)
        else:
            record.update(item.properties)
        
        # Add asset URLs (useful for downloading)
        for asset_key, asset in item.assets.items():
            record[f'asset_{asset_key}_href'] = asset.href
            record[f'asset_{asset_key}_type'] = asset.media_type
        
        records.append(record)
    
    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(records, crs='EPSG:4326')
    
    return gdf
    
def create_site_dict_from_gdf(sites_gdf, site_name_field='Site_Name', buffer_degrees=0.1):
    """
    Create a dictionary with site info including bbox and coordinates
    
    Parameters:
    -----------
    sites_gdf : GeoDataFrame
        GeoDataFrame with site geometries (Point or Polygon)
    site_name_field : str
        Column name containing site names (default 'Site_Name')
    buffer_degrees : float
        Buffer size in degrees around point to create bbox (default 0.1)
        Ignored if geometry is already a Polygon
    
    Returns:
    --------
    dict : Dictionary with site names as keys and site info as values
    """
    site_dict = {}
    
    for idx, row in sites_gdf.iterrows():
        site_name = row[site_name_field]
        geom = row['geometry']
        
        # Skip if geometry is None or invalid
        if geom is None or geom.is_empty:
            print(f"Warning: Invalid geometry for {site_name}, skipping")
            continue
        
        # Handle different geometry types
        if geom.geom_type == 'Point':
            # Point geometry - create bbox with buffer
            lon = geom.x
            lat = geom.y
            
            # Check for NaN coordinates
            if np.isnan(lon) or np.isnan(lat):
                print(f"Warning: NaN coordinates for {site_name}, skipping")
                continue
            
            bbox = [
                lon - buffer_degrees,
                lat - buffer_degrees,
                lon + buffer_degrees,
                lat + buffer_degrees
            ]
        
        elif geom.geom_type == 'Polygon':
            # Polygon geometry - use bounds
            minx, miny, maxx, maxy = geom.bounds
            
            # Check for NaN in bounds
            if any(np.isnan([minx, miny, maxx, maxy])):
                print(f"Warning: NaN in bounds for {site_name}, skipping")
                continue
            
            bbox = [minx, miny, maxx, maxy]
            
            # Get centroid for center coordinates
            centroid = geom.centroid
            lon = centroid.x
            lat = centroid.y
        
        else:
            print(f"Warning: Unsupported geometry type '{geom.geom_type}' for {site_name}")
            continue
        
        site_dict[site_name] = {
            'bbox': bbox,
            'lon': lon,
            'lat': lat,
            'buffer': buffer_degrees,
            'geom_type': geom.geom_type
        }
    
    return site_dict

def stac_search_site(site_tuple, end_date, start_date='2010-01-01', collections=['satellogic'], 
                DICT_QUERY={
                            #'eo:cloud_cover': {'lt': 50},  # Less than 20% cloud cover
                    
                            }
               ):
    """Search a single site"""
    from pystac_client import Client
    import numpy as np
    
    site_name, site_info = site_tuple
    bbox = site_info['bbox']
    
    # Validate bbox
    if bbox is None or len(bbox) != 4 or any(np.isnan(bbox)):
        return (site_name, None, "Invalid bbox")
    
    try:
        catalog = Client.open('https://csdap.earthdata.nasa.gov/stac')
        
        search = catalog.search(
            bbox=bbox,
            datetime=f'{start_date}/{end_date}',
            collections=collections,
            max_items=None,
            # Property filters (if supported)
            query=DICT_QUERY
        )
        
        items = list(search.items())
        
        if len(items) > 0:
            gdf = stac_items_to_gdf(items)
            gdf['site_name'] = site_name
            return (site_name, gdf, f"Found {len(items)} items")
        else:
            return (site_name, None, "No items found")
    
    except Exception as e:
        return (site_name, None, f"Error: {str(e)}")

def plot_collections_map(gdf, collection_field='collection', collections=None, suptitle=None, site_name_field='site_name',
                        figsize=None, alpha=0.4, linewidth=0.5, 
                        show_stats=True):
    """
    Create overview maps with optional statistics using contextily basemap
    """
    
    if collections is None:
        collections = sorted(gdf[collection_field].unique())
    
    n_collections = len(collections)
    
    # Layout
    if n_collections == 1:
        ncols = 1
        nrows = 1
    elif n_collections == 2:
        ncols = 2
        nrows = 1
    elif n_collections <= 4:
        ncols = 2
        nrows = 2
    elif n_collections <= 6:
        ncols = 3
        nrows = 2
    else:
        ncols = 3
        nrows = (n_collections + 2) // 3
    
    if figsize is None:
        figsize = (8 * ncols, 6 * nrows)
    
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)
    axes = axes.flatten()
    
    for idx, collection in enumerate(collections):
        ax = axes[idx]
        
        gdf_collection = gdf[gdf[collection_field] == collection].copy()
        
        if len(gdf_collection) == 0:
            ax.set_title(f'{collection}\nNo data', fontsize=12, fontweight='bold')
            ax.axis('off')
            continue
        
        # Reproject to Web Mercator for contextily
        gdf_merc = gdf_collection.to_crs(epsg=3857)
        
        # Add contextily Esri WorldGrayCanvas basemap
        ctx.add_basemap(
            ax,
            source=ctx.providers.Esri.WorldGrayCanvas,
            crs=gdf_merc.crs.to_string(),
            attribution=False,
            zorder=0
        )

        # Calculate centroids
        gdf_merc['centroid'] = gdf_merc.geometry.centroid
        
        # Create GeoDataFrame with centroids
        gdf_merc = gdf_merc.set_geometry('centroid')
        
        # Plot footprints
        gdf_merc.plot(
            ax=ax,
            facecolor='none',
            edgecolor='red',
            linewidth=linewidth,
            alpha=alpha,
            zorder=2
        )
        
        # Set extent
        minx, miny, maxx, maxy = gdf_merc.total_bounds
        width = maxx - minx
        height = maxy - miny
        buffer = max(width, height) * 0.05
        
        ax.set_xlim(minx - buffer, maxx + buffer)
        ax.set_ylim(miny - buffer, maxy + buffer)
        
        # Build title
        title = f'{collection}\n{len(gdf_collection):,} acquisitions'
        
        # Add stats if requested
        if show_stats and site_name_field in gdf_collection.columns:
            n_sites = gdf_collection[site_name_field].nunique()
            title += f'\n{n_sites} sites'
        
        ax.set_title(title, fontsize=11, fontweight='bold')
        
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_aspect('equal', adjustable='box')

        # Add basemap
        ctx.add_basemap(
            ax,
            source=ctx.providers.Esri.WorldGrayCanvas,
            crs=gdf_merc.crs.to_string(),
            attribution=False,
            zorder=0
        )
    
    # Hide unused
    for idx in range(n_collections, len(axes)):
        axes[idx].axis('off')

    if suptitle is None:
        suptitle = 'CSDA Program STAC Records for Evaluation Sites'
        
    plt.suptitle(suptitle, 
                fontsize=14, fontweight='bold', y=0.995)
    
    plt.tight_layout()
    
    return fig

def create_acquisition_heatmap_multi(gdf, sites_gdf, sites_gdf_buf_display, 
                                     site_name_field='site_name', 
                                     site_name_field_sites='Site_Name',
                                     collections=None, sites=None, grid_size=0.01, 
                                     cmap='turbo', figsize=None):
    """
    Create multiple heatmaps by collection and site with shared colormap
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        GeoDataFrame with acquisition footprints
    sites_gdf : GeoDataFrame
        GeoDataFrame with site geometries
    sites_gdf_buf_display : GeoDataFrame
        GeoDataFrame with buffered site geometries for display
    site_name_field : str
        Column name containing site names in gdf (default 'site_name')
    site_name_field_sites : str
        Column name containing site names in sites_gdf and sites_gdf_buf_display 
        (default 'Site_Name')
    collections : list, optional
        List of collections to plot. If None, uses all unique collections.
    sites : list, optional
        List of sites to plot. If None, uses all unique sites.
    grid_size : float
        Grid cell size in degrees (default 0.01)
    cmap : str
        Matplotlib colormap name (default 'turbo')
    figsize : tuple, optional
        Figure size (width, height). If None, auto-calculated.
    
    Returns:
    --------
    all_grids : dict
        Dictionary of grid GeoDataFrames by (site, collection)
    fig : matplotlib.figure.Figure
        The figure object
    """
    
    # Get unique collections and sites
    if collections is None:
        collections = sorted(gdf['collection'].unique())
    
    if sites is None:
        sites = sorted(gdf[site_name_field].unique())
    
    n_sites = len(sites)
    n_collections = len(collections)
    
    # Determine subplot layout
    ncols = n_collections
    nrows = n_sites
    
    # Auto-calculate figure size if not provided
    if figsize is None:
        figsize = (6 * ncols, 5 * nrows)
    
    # Create figure with extra space at top for colorbar
    fig = plt.figure(figsize=figsize)
    
    # Create gridspec with extra row for colorbar (thinner)
    gs = fig.add_gridspec(nrows + 1, ncols, height_ratios=[0.15] + [1]*nrows, 
                          hspace=0.3, wspace=0.2)
    
    
    all_grids = {}
    
    # First pass: calculate global min/max for shared colormap
    vmin = float('inf')
    vmax = float('-inf')
    
    print("Calculating global count range...")
    for site in sites:
        for collection in collections:
            gdf_filtered = gdf[
                (gdf[site_name_field] == site) & 
                (gdf['collection'] == collection)
            ].copy()
            
            if len(gdf_filtered) == 0:
                continue
            
            gdf_filtered_merc = gdf_filtered.to_crs(epsg=3857)
            minx, miny, maxx, maxy = gdf_filtered_merc.total_bounds
            
            grid_size_meters = grid_size * 111000
            buffer = grid_size_meters * 2
            
            x_coords = np.arange(minx - buffer, maxx + buffer, grid_size_meters)
            y_coords = np.arange(miny - buffer, maxy + buffer, grid_size_meters)
            
            grid_cells = [box(x, y, x + grid_size_meters, y + grid_size_meters) 
                         for x in x_coords for y in y_coords]
            grid_gdf = gpd.GeoDataFrame({'geometry': grid_cells}, crs='EPSG:3857')
            
            joined = gpd.sjoin(grid_gdf, gdf_filtered_merc, how='left', predicate='intersects')
            counts = joined.groupby(joined.index).size()
            
            if len(counts) > 0:
                vmin = min(vmin, counts.min())
                vmax = max(vmax, counts.max())
    
    if vmin == float('inf'):
        vmin, vmax = 0, 1
    
    print(f"Global count range: {vmin} - {vmax}")
    
    # Create normalization and colormap
    norm = Normalize(vmin=vmin, vmax=vmax)
    cmap_obj = plt.get_cmap(cmap)
    
    # Create colorbar in top row spanning all columns
    cbar_ax = fig.add_subplot(gs[0, :])
    sm = ScalarMappable(cmap=cmap_obj, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax, orientation='horizontal', 
                       label='Number of Acquisitions per Grid Cell')
    cbar.ax.tick_params(labelsize=9)  # Also made tick labels slightly smaller
    cbar.set_label('Number of Acquisitions per Grid Cell', fontsize=10)  # Control label size
    
    # Create main plot axes
    axes = []
    for row in range(nrows):
        row_axes = []
        for col in range(ncols):
            ax = fig.add_subplot(gs[row + 1, col])
            row_axes.append(ax)
        axes.append(row_axes)
    
    # Second pass: plot everything
    for row_idx, site in enumerate(sites):
        for col_idx, collection in enumerate(collections):
            ax = axes[row_idx][col_idx]
            
            # Get site geometries
            site_geom_row = sites_gdf[sites_gdf[site_name_field_sites] == site]
            site_buf_row = sites_gdf_buf_display[sites_gdf_buf_display[site_name_field_sites] == site]
            
            if len(site_geom_row) == 0:
                ax.set_title(f'{site}\n{collection}\nSite not found', fontsize=10)
                ax.axis('off')
                continue
            
            site_geom = site_geom_row.iloc[0].geometry
            
            # Get centroid
            if site_geom.geom_type == 'Point':
                centroid = site_geom
            else:
                centroid = site_geom.centroid
            
            # Filter data
            gdf_filtered = gdf[
                (gdf[site_name_field] == site) & 
                (gdf['collection'] == collection)
            ].copy()
            
            # Reproject to Web Mercator
            site_buf_merc = site_buf_row.to_crs(epsg=3857)
            
            # Plot buffered site boundary
            if len(site_buf_merc) > 0:
                site_buf_merc.plot(
                    ax=ax,
                    facecolor='none',
                    edgecolor='red',
                    linewidth=2,
                    linestyle='--',
                    alpha=0.8,
                    zorder=5
                )
            
            # Handle no data case
            if len(gdf_filtered) == 0:
                # Add basemap
                if len(site_buf_merc) > 0:
                    ctx.add_basemap(
                        ax,
                        source=ctx.providers.Esri.WorldGrayCanvas,
                        crs=site_buf_merc.crs.to_string(),
                        attribution=False,
                        zorder=0
                    )
                
                # Plot centroid
                centroid_merc = gpd.GeoSeries([centroid], crs='EPSG:4326').to_crs(epsg=3857)
                ax.plot(centroid_merc.x, centroid_merc.y, 'r*', markersize=15, 
                       markeredgecolor='black', markeredgewidth=1, zorder=10)
                
                ax.set_title(f'{site}\n{collection}\nNo data', fontsize=10, fontweight='bold')
                
                if len(site_buf_merc) > 0:
                    minx, miny, maxx, maxy = site_buf_merc.total_bounds
                    ax.set_xlim(minx, maxx)
                    ax.set_ylim(miny, maxy)
                
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_aspect('equal', adjustable='box')
                continue
            
            # Reproject filtered data
            gdf_filtered_merc = gdf_filtered.to_crs(epsg=3857)
            
            # Get bounds for grid
            minx, miny, maxx, maxy = gdf_filtered_merc.total_bounds
            grid_size_meters = grid_size * 111000
            buffer = grid_size_meters * 2
            minx -= buffer
            miny -= buffer
            maxx += buffer
            maxy += buffer
            
            # Create grid
            x_coords = np.arange(minx, maxx, grid_size_meters)
            y_coords = np.arange(miny, maxy, grid_size_meters)
            
            grid_cells = []
            for x in x_coords:
                for y in y_coords:
                    cell = box(x, y, x + grid_size_meters, y + grid_size_meters)
                    grid_cells.append(cell)
            
            grid_gdf = gpd.GeoDataFrame({'geometry': grid_cells}, crs='EPSG:3857')
            
            # Count acquisitions
            joined = gpd.sjoin(grid_gdf, gdf_filtered_merc, how='left', predicate='intersects')
            counts = joined.groupby(joined.index).size()
            grid_gdf['count'] = 0
            grid_gdf.loc[counts.index, 'count'] = counts.values
            grid_gdf_filtered = grid_gdf[grid_gdf['count'] > 0].copy()
            
            # Store grid
            all_grids[(site, collection)] = grid_gdf_filtered.to_crs(epsg=4326)
            
            # Add basemap
            if len(site_buf_merc) > 0:
                ctx.add_basemap(
                    ax,
                    source=ctx.providers.Esri.WorldGrayCanvas,
                    crs=gdf_filtered_merc.crs.to_string(),
                    attribution=False,
                    zorder=0
                )
            
            # Plot heatmap with shared colormap (no individual legend)
            if len(grid_gdf_filtered) > 0:
                grid_gdf_filtered.plot(
                    column='count',
                    cmap=cmap_obj,
                    norm=norm,
                    legend=False,  # No individual legends
                    ax=ax,
                    edgecolor='none',
                    linewidth=0,
                    alpha=0.7,
                    zorder=2
                )
            
            # Overlay footprints
            gdf_filtered_merc.plot(
                ax=ax,
                facecolor='none',
                edgecolor='white',
                linewidth=0.3,
                alpha=0.4,
                zorder=3
            )
            
            # Plot centroid
            centroid_merc = gpd.GeoSeries([centroid], crs='EPSG:4326').to_crs(epsg=3857)
            ax.plot(centroid_merc.x, centroid_merc.y, 'r*', markersize=15, 
                   markeredgecolor='black', markeredgewidth=1, zorder=10)
            
            # Set extent
            if len(site_buf_merc) > 0:
                buf_minx, buf_miny, buf_maxx, buf_maxy = site_buf_merc.total_bounds
                ax.set_xlim(buf_minx, buf_maxx)
                ax.set_ylim(buf_miny, buf_maxy)
            
            # Title
            ax.set_title(f'{site}\n{collection}\n{len(gdf_filtered)} acquisitions',
                        fontsize=10, fontweight='bold')
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect('equal', adjustable='box')
    
    # Overall title
    fig.suptitle(f'Acquisition Density Heatmaps by Site and Collection (Grid: {grid_size}°)', 
                fontsize=14, fontweight='bold', y=0.995)
    
    return all_grids, fig

def create_interactive_heatmap(gdf, collection_name=None, grid_size=0.1, 
                               cmap='turbo', site_name='PICS Libya-4'):
    """
    Create interactive heatmap with folium as a single named layer
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        Acquisition footprints
    collection_name : str, optional
        Collection to filter by
    grid_size : float
        Grid cell size in degrees
    cmap : str
        Matplotlib colormap name
    site_name : str
        Name of the site for the legend
    """
    # Filter by collection
    if collection_name:
        gdf_filtered = gdf[gdf['collection'] == collection_name].copy()
        collection_label = collection_name.title()
    else:
        gdf_filtered = gdf.copy()
        collection_label = "All Collections"

    # Filter by site_name
    gdf_filtered = gdf_filtered[gdf_filtered['site_name'] == site_name]
    
    print(f"Creating heatmap for {len(gdf_filtered)} acquisitions")
    
    # Create grid
    minx, miny, maxx, maxy = gdf_filtered.total_bounds
    buffer = grid_size * 2
    minx -= buffer
    miny -= buffer
    maxx += buffer
    maxy += buffer
    
    x_coords = np.arange(minx, maxx, grid_size)
    y_coords = np.arange(miny, maxy, grid_size)
    
    grid_cells = []
    for x in x_coords:
        for y in y_coords:
            cell = box(x, y, x + grid_size, y + grid_size)
            grid_cells.append(cell)
    
    grid_gdf = gpd.GeoDataFrame({'geometry': grid_cells}, crs=gdf_filtered.crs)
    
    # Count acquisitions
    joined = gpd.sjoin(grid_gdf, gdf_filtered, how='left', predicate='intersects')
    counts = joined.groupby(joined.index).size()
    grid_gdf['count'] = 0
    grid_gdf.loc[counts.index, 'count'] = counts.values
    grid_gdf = grid_gdf[grid_gdf['count'] > 0].copy()
    
    print(f"Grid cells with data: {len(grid_gdf)}")
    print(f"Acquisition count range: {grid_gdf['count'].min()} - {grid_gdf['count'].max()}")
    
    # Get date range
    date_str = "unknown_dates"
    if 'datetime' in gdf_filtered.columns:
        dates = gdf_filtered['datetime'].dropna()
        if len(dates) > 0:
            try:
                # Handle different datetime formats
                dates_converted = []
                for d in dates:
                    if isinstance(d, str):
                        dates_converted.append(datetime.fromisoformat(d.replace('Z', '+00:00')))
                    else:
                        dates_converted.append(d)
                
                start_date = min(dates_converted)
                end_date = max(dates_converted)
                date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
            except Exception as e:
                print(f"Could not parse dates: {e}")
    
    # Create layer name
    layer_name = f"{site_name} {collection_label} {date_str}"
    
    # Create map
    center_lat = (miny + maxy) / 2
    center_lon = (minx + maxx) / 2
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)
    
    # Get matplotlib colormap and convert to hex colors
    min_count = grid_gdf['count'].min()
    max_count = grid_gdf['count'].max()
    
    mpl_cmap = plt.get_cmap(cmap)
    n_colors = 256
    colors = [mcolors.rgb2hex(mpl_cmap(i / n_colors)) for i in range(n_colors)]
    
    # Create branca colormap
    colormap = cm.LinearColormap(
        colors=colors,
        vmin=min_count,
        vmax=max_count,
        caption=f'Acquisitions per {grid_size}° cell'
    )
    
    # Create style function
    def style_function(feature):
        count = feature['properties']['count']
        color = colormap(count)
        return {
            'fillColor': color,
            'color': 'gray',
            'weight': 0.5,
            'fillOpacity': 0.7
        }
    
    # Add single GeoJson layer
    folium.GeoJson(
        grid_gdf,
        name=layer_name,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['count'],
            aliases=['Acquisitions:'],
            localize=True,
            sticky=False,
            labels=True,
            style="""
                background-color: #F0EFEF;
                border: 2px solid black;
                border-radius: 3px;
                box-shadow: 3px;
            """,
        )
    ).add_to(m)
    
    # Add colormap legend
    colormap.add_to(m)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    # Add title
    title_html = f'''
        <div style="position: fixed; 
                    top: 10px; left: 50px; width: 400px; height: 50px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:14px; padding: 10px">
        <b>{layer_name}</b><br>
        Total acquisitions: {len(gdf_filtered)} | Grid cells: {len(grid_gdf)}
        </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    return m, grid_gdf
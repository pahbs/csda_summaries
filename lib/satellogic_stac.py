"""
Satellogic STAC Client Wrapper
Provides a requests-based interface that mimics pystac_client
"""

import requests
import json
from datetime import datetime
from shapely.geometry import shape, mapping


class SatellogicSTACClient:
    """
    Wrapper for Satellogic STAC API using requests
    Mimics pystac_client.Client interface
    """
    
    def __init__(self, auth):
        """
        Initialize client
        
        Parameters:
        -----------
        auth : SatellogicAuth
            Authentication manager instance
        """
        self.auth = auth
        self.stac_url = "https://api.satellogic.com/v2/archive"
        
    def search(self, bbox=None, datetime=None, collections=None, max_items=None, **kwargs):
        """
        Search STAC catalog
        
        Parameters:
        -----------
        bbox : list
            Bounding box [west, south, east, north]
        datetime : str
            Date range in format 'YYYY-MM-DD/YYYY-MM-DD'
        collections : list
            List of collection IDs
        max_items : int, optional
            Maximum number of items to return
            
        Returns:
        --------
        SatellogicSTACSearch : Search results object
        """
        return SatellogicSTACSearch(
            self.auth,
            self.stac_url,
            bbox=bbox,
            datetime=datetime,
            collections=collections,
            max_items=max_items,
            **kwargs
        )


class SatellogicSTACSearch:
    """Handles STAC search execution and result iteration"""
    
    def __init__(self, auth, stac_url, bbox=None, datetime=None, 
                 collections=None, max_items=None, **kwargs):
        self.auth = auth
        self.stac_url = stac_url
        self.bbox = bbox
        self.datetime = datetime
        self.collections = collections
        self.max_items = max_items
        self.kwargs = kwargs
        
    def _normalize_datetime(self, dt_str):
        """
        Convert date or datetime string to ISO 8601 format with time component
        
        Parameters:
        -----------
        dt_str : str
            Date string in format 'YYYY-MM-DD' or 'YYYY-MM-DD/YYYY-MM-DD'
            
        Returns:
        --------
        str : ISO 8601 datetime string(s)
        """
        if not dt_str:
            return None
            
        # Handle interval format
        if '/' in dt_str:
            start, end = dt_str.split('/')
            start_iso = self._add_time_component(start, is_start=True)
            end_iso = self._add_time_component(end, is_start=False)
            return f"{start_iso}/{end_iso}"
        else:
            return self._add_time_component(dt_str, is_start=True)
    
    def _add_time_component(self, dt_str, is_start=True):
        """
        Add time component to date string if missing
        
        Parameters:
        -----------
        dt_str : str
            Date or datetime string
        is_start : bool
            If True, use 00:00:00Z; if False, use 23:59:59Z
            
        Returns:
        --------
        str : ISO 8601 datetime string
        """
        dt_str = dt_str.strip()
        
        # Already has time component
        if 'T' in dt_str or ' ' in dt_str:
            # Ensure it ends with Z
            if not dt_str.endswith('Z'):
                dt_str += 'Z'
            return dt_str
        
        # Add time component
        if is_start:
            return f"{dt_str}T00:00:00Z"
        else:
            return f"{dt_str}T23:59:59Z"
        
    def items(self):
        """
        Execute search and yield items
        
        Yields:
        -------
        dict : STAC item as dictionary (compatible with stac_items_to_gdf)
        """
        # Build search payload
        payload = {}
        
        if self.bbox:
            payload['bbox'] = self.bbox
            
        if self.datetime:
            # Normalize datetime to ISO 8601 format
            payload['datetime'] = self._normalize_datetime(self.datetime)
            
        if self.collections:
            payload['collections'] = self.collections
            
        if self.max_items:
            payload['limit'] = self.max_items
        else:
            payload['limit'] = 1000  # Default limit per page
            
        # Add any additional query parameters
        payload.update(self.kwargs)
        
        # Execute search with pagination
        headers = self.auth.get_headers()
        search_url = f"{self.stac_url}/search"
        
        total_items = 0
        
        while True:
            try:
                response = requests.post(search_url, headers=headers, json=payload)
                
                if response.status_code != 200:
                    # Provide detailed error message
                    error_detail = response.text
                    raise Exception(f"Search failed: {response.status_code} - {error_detail}")
                
                results = response.json()
                features = results.get('features', [])
                
                if not features:
                    break
                    
                for feature in features:
                    # Convert to pystac-like item structure
                    item = self._convert_to_pystac_item(feature)
                    yield item
                    
                    total_items += 1
                    if self.max_items and total_items >= self.max_items:
                        return
                
                # Check for next page
                links = results.get('links', [])
                next_link = next((link for link in links if link.get('rel') == 'next'), None)
                
                if not next_link:
                    break
                    
                # Update search URL for next page
                search_url = next_link['href']
                payload = {}  # Next link contains all parameters
                
            except requests.exceptions.RequestException as e:
                raise Exception(f"Request failed: {str(e)}")
            
    def _convert_to_pystac_item(self, feature):
        """
        Convert Satellogic STAC feature to pystac-like item
        
        Parameters:
        -----------
        feature : dict
            GeoJSON feature from Satellogic STAC
            
        Returns:
        --------
        SatellogicSTACItem : Item object with pystac-like interface
        """
        return SatellogicSTACItem(feature)


class SatellogicSTACItem:
    """
    Wrapper for STAC item that provides pystac-like interface
    """
    
    def __init__(self, feature):
        self._feature = feature
        
    @property
    def id(self):
        return self._feature.get('id')
    
    @property
    def collection_id(self):
        """Get collection ID with fallback"""
        # Try different possible field names
        return (self._feature.get('collection') or 
                self._feature.get('collection_id') or
                self.properties.get('collection') or
                'unknown')
    
    @property
    def geometry(self):
        return self._feature.get('geometry')
    
    @property
    def bbox(self):
        return self._feature.get('bbox')
    
    @property
    def properties(self):
        return self._feature.get('properties', {})
    
    @property
    def datetime(self):
        """Parse datetime from properties"""
        # Try different datetime fields
        dt_str = (self.properties.get('datetime') or 
                  self.properties.get('start_datetime') or
                  self._feature.get('datetime'))
        
        if dt_str:
            try:
                return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            except:
                pass
        return None
    
    @property
    def assets(self):
        return self._feature.get('assets', {})
    
    def to_dict(self):
        """Return original feature dictionary"""
        return self._feature
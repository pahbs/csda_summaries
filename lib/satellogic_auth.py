"""
Satellogic API Authentication Module
Handles credential loading and token management
"""

import configparser
import requests
import json
from datetime import datetime, timedelta


class SatellogicAuth:
    """Manages Satellogic API authentication"""
    
    def __init__(self, credentials_path):
        """
        Initialize authentication
        
        Parameters:
        -----------
        credentials_path : str
            Path to credentials.ini file
        """
        self.credentials_path = credentials_path
        self.access_token = None
        self.token_expiry = None
        self.contract_id = None
        
        # Load credentials
        self._load_credentials()
        
    def _load_credentials(self):
        """Read credentials from INI file"""
        config = configparser.ConfigParser()
        config.read(self.credentials_path)
        
        self.client_id = config.get('Satellogic_STAC_API', 'client_id')
        self.client_secret = config.get('Satellogic_STAC_API', 'client_secret')
        
    def get_access_token(self, force_refresh=False):
        """
        Get valid access token, refreshing if needed
        
        Parameters:
        -----------
        force_refresh : bool
            Force token refresh even if current token is valid
            
        Returns:
        --------
        str : Valid access token
        """
        # Check if we need to refresh
        if (force_refresh or 
            self.access_token is None or 
            self.token_expiry is None or 
            datetime.now() >= self.token_expiry - timedelta(minutes=5)):
            
            self._refresh_token()
            
        return self.access_token
    
    def _refresh_token(self):
        """Request new access token from Satellogic"""
        auth_url = 'https://auth.platform.satellogic.com/oauth/token'
        auth_payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": "https://api.satellogic.com/",
            "grant_type": "client_credentials"
        }
        
        response = requests.post(
            auth_url,
            headers={'content-type': 'application/json'},
            data=json.dumps(auth_payload)
        )
        
        if response.status_code != 200:
            raise Exception(f"Authentication failed: {response.status_code} - {response.text}")
        
        auth_data = response.json()
        self.access_token = auth_data['access_token']
        self.token_expiry = datetime.now() + timedelta(seconds=auth_data.get('expires_in', 86400))
        
    def get_contract_id(self):
        """
        Retrieve contract ID from Satellogic API
        
        Returns:
        --------
        str : Contract ID
        """
        if self.contract_id is not None:
            return self.contract_id
            
        # Ensure we have a valid token
        token = self.get_access_token()
        
        contracts_url = 'https://api.satellogic.com/contracts'
        response = requests.get(
            contracts_url,
            headers={'authorizationToken': f'Bearer {token}'}
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to retrieve contracts: {response.status_code} - {response.text}")
        
        contracts = response.json()
        
        if not contracts:
            raise Exception("No contracts found for this account")
        
        self.contract_id = contracts[0]['contract_id']
        return self.contract_id
    
    def get_headers(self):
        """
        Get authentication headers for API requests
        
        Returns:
        --------
        dict : Headers dictionary
        """
        return {
            "authorizationToken": f"Bearer {self.get_access_token()}",
            "X-Satellogic-Contract-Id": self.get_contract_id(),
            "Content-Type": "application/json",
        }
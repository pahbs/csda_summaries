# sensor_lookup_table.json or sensor_lookup_table.py

SENSOR_LOOKUP = {
    # BlackSky constellation
    'BLACKSKY': {
        'affiliation': 'BlackSky',
        'constellation': 'BlackSky',
        'patterns': ['BLACKSKY', 'BSK'],
        'sensors': {
            'GLOBAL': {'name': 'BlackSky Global', 'resolution': 1.0}
            }
    },
# Pixxel Firefly constellation (Hyperspectral)
'PIXXEL': {
    'affiliation': 'Pixxel',
    'constellation': 'Firefly',
    'patterns': ['PIXXEL', 'FF01', 'FF02', 'FF03', 'FF04', 'FF05', 'FF06'],
    'sensors': {
        'FF01': {'name': 'Firefly-1', 'launch_year': 2024, 'sensor_type': 'Hyperspectral', 
                 'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'},
        'FF02': {'name': 'Firefly-2', 'launch_year': 2024, 'sensor_type': 'Hyperspectral', 
                 'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'},
        'FF03': {'name': 'Firefly-3', 'launch_year': 2024, 'sensor_type': 'Hyperspectral', 
                 'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'},
        'FF04': {'name': 'Firefly-4', 'launch_year': 2024, 'sensor_type': 'Hyperspectral', 
                 'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'},
        'FF05': {'name': 'Firefly-5', 'launch_year': 2025, 'sensor_type': 'Hyperspectral', 
                 'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'},
        'FF06': {'name': 'Firefly-6', 'launch_year': 2025, 'sensor_type': 'Hyperspectral', 
                 'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'},
        'PIXXEL': {'name': 'Pixxel', 'launch_year': 2024, 'sensor_type': 'Hyperspectral', 
                   'resolution_ms': 5.0, 'num_bands': 45, 'spectral_range': 'VNIR'}
    }
},
    # Satellogic Aleph-1 constellation (all generations use "Aleph1" constellation name)
    'SATELLOGIC': {
        'affiliation': 'Satellogic',
        'constellation': 'Aleph-1',  # Satellogic uses "Aleph1" for all
        'patterns': ['SATELLOGIC', 'NEWSAT', 'ALEPH', '_SN', 'SN01', 'SN02', 'SN03', 'SN04', 'SN05', 'SN06', 'SN07', 'SN08', 'SN09', 'SN10', 
                     'SN11', 'SN12', 'SN13', 'SN14', 'SN15', 'SN16', 'SN17', 'SN18', 'SN19', 'SN20',
                     'SN21', 'SN22', 'SN23', 'SN24', 'SN25', 'SN26', 'SN27', 'SN28', 'SN29', 'SN30',
                 'SN31', 'SN32', 'SN33', 'SN34', 'SN35', 'SN36', 'SN37', 'SN38', 'SN39', 'SN40',
                 'SN41', 'SN42', 'SN43', 'SN44', 'SN45', 'SN46', 'SN47', 'SN48', 'SN49', 'SN50'],
        'sensors': {
            # Mark-II Generation (1.0m resolution)
            'SN01': {'name': 'NewSat-1', 'launch_year': 2017, 'generation': '', 'resolution_ms': 1.0},
            'SN02': {'name': 'NewSat-2', 'launch_year': 2017, 'generation': '', 'resolution_ms': 1.0},
            
            # Mark-III Generation (1.0m resolution) - SN03-SN18
            # Mark-IV & Mark-V (0.7m resolution) - SN19 onwards
            # Using GSD from STAC to determine generation dynamically
            'SN03': {'name': 'NewSat-3', 'launch_year': 2018, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN04': {'name': 'NewSat-4', 'launch_year': 2018, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN05': {'name': 'NewSat-5', 'launch_year': 2018, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN06': {'name': 'NewSat-6', 'launch_year': 2018, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN07': {'name': 'NewSat-7', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN08': {'name': 'NewSat-8', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN09': {'name': 'NewSat-9', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN10': {'name': 'NewSat-10', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN11': {'name': 'NewSat-11', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN12': {'name': 'NewSat-12', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN13': {'name': 'NewSat-13', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN14': {'name': 'NewSat-14', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN15': {'name': 'NewSat-15', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN16': {'name': 'NewSat-16', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN17': {'name': 'NewSat-17', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN18': {'name': 'NewSat-18', 'launch_year': 2019, 'generation': 'Mark-IV', 'resolution_ms': 1.0},
            'SN19': {'name': 'NewSat-19', 'launch_year': 2020, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN20': {'name': 'NewSat-20', 'launch_year': 2020, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN21': {'name': 'NewSat-21', 'launch_year': 2020, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN22': {'name': 'NewSat-22', 'launch_year': 2020, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN23': {'name': 'NewSat-23', 'launch_year': 2021, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN24': {'name': 'NewSat-24', 'launch_year': 2021, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN25': {'name': 'NewSat-25', 'launch_year': 2021, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN26': {'name': 'NewSat-26', 'launch_year': 2021, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN27': {'name': 'NewSat-27', 'launch_year': 2021, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN28': {'name': 'NewSat-28', 'launch_year': 2021, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN29': {'name': 'NewSat-29', 'launch_year': 2022, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN30': {'name': 'NewSat-30', 'launch_year': 2022, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN31': {'name': 'NewSat-31', 'launch_year': 2022, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN32': {'name': 'NewSat-32', 'launch_year': 2022, 'generation': 'Mark-IV', 'resolution_ms': 0.7},
            'SN33': {'name': 'NewSat-33', 'launch_year': 2023, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN34': {'name': 'NewSat-34', 'launch_year': 2023, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN35': {'name': 'NewSat-35', 'launch_year': 2023, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN36': {'name': 'NewSat-36', 'launch_year': 2023, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN37': {'name': 'NewSat-37', 'launch_year': 2023, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN38': {'name': 'NewSat-38', 'launch_year': 2023, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN39': {'name': 'NewSat-39', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN40': {'name': 'NewSat-40', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN41': {'name': 'NewSat-41', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN42': {'name': 'NewSat-42', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN43': {'name': 'NewSat-43', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN44': {'name': 'NewSat-44', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN45': {'name': 'NewSat-45', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN46': {'name': 'NewSat-46', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN47': {'name': 'NewSat-47', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN48': {'name': 'NewSat-48', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN49': {'name': 'NewSat-49', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            'SN50': {'name': 'NewSat-50', 'launch_year': 2024, 'generation': 'Mark-V', 'resolution_ms': 0.7},
            
            'SATELLOGIC': {'name': 'Satellogic', 'launch_year': 2020, 'generation': 'Unknown', 'resolution_ms': 0.7}
        }
    },
    # Airbus Pleiades Neo constellation
    'PNEO': {
        'affiliation': 'Airbus',
        'constellation': 'Pleiades Neo',
        'patterns': ['PNEO', 'PLEIADES NEO', 'PLEIADES-NEO'],
        'sensors': {
            'PNEO3': {'name': 'PNEO3', 'launch_year': 2021, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'PNEO4': {'name': 'PNEO4', 'launch_year': 2021, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'PNEO5': {'name': 'PNEO5', 'launch_year': 2022, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'PNEO6': {'name': 'PNEO6', 'launch_year': 2022, 'resolution_pan': 0.3, 'resolution_ms': 1.2}
        }
    },
    
    # Airbus Pleiades (original)
    'PHR': {
        'affiliation': 'Airbus',
        'constellation': 'Pleiades',
        'patterns': ['PHR', 'PLEIADES'],
        'sensors': {
            'PHR1A': {'name': 'Pleiades1A', 'launch_year': 2011, 'resolution_pan': 0.5, 'resolution_ms': 2.0},
            'PHR1B': {'name': 'Pleiades1B', 'launch_year': 2012, 'resolution_pan': 0.5, 'resolution_ms': 2.0}
        }
    },
    
    # Airbus SPOT constellation
    'SPOT': {
        'affiliation': 'Airbus',
        'constellation': 'SPOT',
        'patterns': ['SPOT', 'SPOT6', 'SPOT7'],
        'sensors': {
            'SPOT6': {'name': 'SPOT6', 'launch_year': 2012, 'resolution_pan': 1.5, 'resolution_ms': 6.0},
            'SPOT7': {'name': 'SPOT7', 'launch_year': 2014, 'resolution_pan': 1.5, 'resolution_ms': 6.0}
        }
    },
    
    # Maxar Legion constellation (UPDATED)
    'LEGION': {
        'affiliation': 'Maxar',
        'constellation': 'Legion',
        'patterns': ['LEGION', 'P3DS', 'M3DS', 'LG01', 'LG02', 'LG03', 'LG04', 'LG05', 'LG06'],
        'sensors': {
            'LG01': {'name': 'Legion-1', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LG02': {'name': 'Legion-2', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LG03': {'name': 'Legion-3', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LG04': {'name': 'Legion-4', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LG05': {'name': 'Legion-5', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LG06': {'name': 'Legion-6', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            # Keep these as fallbacks
            'LEGION1': {'name': 'Legion-1', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LEGION2': {'name': 'Legion-2', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LEGION3': {'name': 'Legion-3', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LEGION4': {'name': 'Legion-4', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LEGION5': {'name': 'Legion-5', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LEGION6': {'name': 'Legion-6', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2},
            'LEGION': {'name': 'Legion', 'launch_year': 2024, 'resolution_pan': 0.3, 'resolution_ms': 1.2}
        }
    },
    
    # Maxar WorldView constellation
    'WV': {
        'affiliation': 'Maxar',
        'constellation': 'WorldView',
        'patterns': ['WV', 'WORLDVIEW'],
        'sensors': {
            'WV01': {'name': 'WorldView-1', 'launch_year': 2007, 'resolution_pan': 0.5},
            'WV02': {'name': 'WorldView-2', 'launch_year': 2009, 'resolution_pan': 0.46, 'resolution_ms': 1.85},
            'WV03': {'name': 'WorldView-3', 'launch_year': 2014, 'resolution_pan': 0.31, 'resolution_ms': 1.24},
            'WV04': {'name': 'WorldView-4', 'launch_year': 2016, 'resolution_pan': 0.31, 'resolution_ms': 1.24}
        }
    },
    
    # Maxar GeoEye
    'GE': {
        'affiliation': 'Maxar',
        'constellation': 'GeoEye',
        'patterns': ['GE', 'GEOEYE'],
        'sensors': {
            'GE01': {'name': 'GeoEye-1', 'launch_year': 2008, 'resolution_pan': 0.41, 'resolution_ms': 1.65}
        }
    },
    
    # Maxar QuickBird
    'QB': {
        'affiliation': 'Maxar',
        'constellation': 'QuickBird',
        'patterns': ['QB', 'QUICKBIRD'],
        'sensors': {
            'QB02': {'name': 'QuickBird', 'launch_year': 2001, 'resolution_pan': 0.61, 'resolution_ms': 2.44}
        }
    },
    
    # Planet Labs SkySat
    'SKYSAT': {
        'affiliation': 'Planet',
        'constellation': 'SkySat',
        'patterns': ['SKYSAT', 'SKY'],
        'sensors': {
            'SKYSAT': {'name': 'SkySat', 'launch_year': 2013, 'resolution_pan': 0.5, 'resolution_ms': 1.0}
        }
    },
    
    # Planet Dove/SuperDove
    'DOVE': {
        'affiliation': 'Planet',
        'constellation': 'Dove',
        'patterns': ['DOVE', 'SUPERDOVE', 'PLANETSCOPE'],
        'sensors': {
            'PS2': {'name': 'PlanetScope', 'resolution': 3.0},
            'PS2.SD': {'name': 'SuperDove', 'resolution': 3.0}
        }
    },
    
    # ESA Sentinel-2
    'S2': {
        'affiliation': 'ESA',
        'constellation': 'Sentinel-2',
        'patterns': ['S2A', 'S2B', 'SENTINEL2', 'SENTINEL-2'],
        'sensors': {
            'S2A': {'name': 'Sentinel-2A', 'launch_year': 2015, 'resolution': 10.0},
            'S2B': {'name': 'Sentinel-2B', 'launch_year': 2017, 'resolution': 10.0}
        }
    },
    
    # NASA/USGS Landsat
    'LANDSAT': {
        'affiliation': 'USGS/NASA',
        'constellation': 'Landsat',
        'patterns': ['LC08', 'LC09', 'LE07', 'LANDSAT'],
        'sensors': {
            'LC08': {'name': 'Landsat-8', 'launch_year': 2013, 'resolution': 30.0},
            'LC09': {'name': 'Landsat-9', 'launch_year': 2021, 'resolution': 30.0},
            'LE07': {'name': 'Landsat-7', 'launch_year': 1999, 'resolution': 30.0}
        }
    },
    
    # ICEYE SAR
    'ICEYE': {
        'affiliation': 'ICEYE',
        'constellation': 'ICEYE',
        'patterns': ['ICEYE'],
        'sensors': {
            'ICEYE': {'name': 'ICEYE', 'sensor_type': 'SAR', 'resolution': 1.0}
        }
    },
    
    # Capella SAR
    'CAPELLA': {
        'affiliation': 'Capella',
        'constellation': 'Capella',
        'patterns': ['CAPELLA'],
        'sensors': {
            'CAPELLA': {'name': 'Capella', 'sensor_type': 'SAR', 'resolution': 0.5}
        }
    }
}

# Update PRODUCT_CODES to include Legion-specific codes
PRODUCT_CODES = [
    'ORT', 'ORTHO', 'SEN', 'SENSOR', 'PRJ', 'PROJECTED',
    'PWOI', 'STD', 'STANDARD', 'STE', 'STEREO',
    'PMS', 'PSH', 'BASIC', 'L1A', 'L1B', 'L1C', 'L2A',
    'GRD', 'SLC', 'RAW',
    'P3DS', 'M3DS'  # Legion product codes - but handle carefully as these identify image type
]

# Update IMAGE_TYPE_PATTERNS to better handle Legion
IMAGE_TYPE_PATTERNS = {
    'P': ['PAN', 'PANCHROMATIC', '_P_', '_PAN_', 'P2DS','P2AS', 'P3DS'],
    'MS': ['MS', 'MUL', 'MULTI', 'MULTISPECTRAL', '_MS_', '_MUL_', 'M2DS', 'M2AS', 'M3DS',  
           'MS-FS', 'MS-N', 'RGBN', 'RGB', 'NED', '-M3DS', 'L1C', 'L2A'],  # Added Pixxel product levels
    'HYPER': ['HYPERSPECTRAL', 'VNIR', 'FF0']  # Add hyperspectral category for Pixxel
}
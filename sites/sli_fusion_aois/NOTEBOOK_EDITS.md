# Notebook edits — `csda_eval_sites_process.ipynb`

These edits wire the staged SLI-FUSION AOIs into the existing pipeline. They use the
`multi_site_geojson_dict` mechanism (one combined GeoJSON per family, matched by a
`name_field`), which is already how the SDB / NEON / USGS AOIs are handled.

## 0. Prerequisite — copy staged files to the sites directory

Copy the five staged files into the directory the notebook reads from (ADAPT/explore):

```
/explore/nobackup/projects/CSDA_eval/sites/sli_fusion_wildfire_aoi.geojson
/explore/nobackup/projects/CSDA_eval/sites/sli_fusion_firesense_aoi.geojson
/explore/nobackup/projects/CSDA_eval/sites/sli_fusion_ard_acquisition_aoi.geojson
/explore/nobackup/projects/CSDA_eval/sites/sli_fusion_bathymetry_aoi.geojson
/explore/nobackup/projects/CSDA_eval/sites/sli_fusion_surfacewater_aoi.geojson
```

(Commit them to `csda_summaries/sites/` so they sync, same as the other AOI files.)

## 1. Add the 41 rows to the Google Sheet "Evaluation Sites" tab

Paste the rows from `new_eval_sites_rows.csv`. Key points:
- `Site Name abbrev` holds the **namespaced key** (e.g. `fire_grasshopper_2026`,
  `firesense_grasshopper_2026`, `CU_h003v009`). `read_from_sheet` uses this as the
  effective `Site Name`, so the three name collisions (Grasshopper, Little Giant,
  Widemouth 2 — each in both the wildfire-demo and FireSense families) stay distinct.
- `Program Use = SLI-FUSION` (a new value). The evaluation geojson is built with
  `CSDA_ONLY=False`, so these rows are included; they do **not** pollute the CSDA /
  corner-reflector set (`CSDA_ONLY=True`, `Program Use == 'CSDA'`).
- `Longitude`/`Latitude` are equal-area centroids (point fallback). `aoi_shape=custom`
  so the real geometry is injected from the GeoJSON in step 3.

## 2. Edit cell 13 — extend `multi_site_geojson_dict`

Add these five entries (each family's combined file, matched on `site_key`):

```python
SLI_FUSION_DIR = '/explore/nobackup/projects/CSDA_eval/sites'

multi_site_geojson_dict.update({
    f'{SLI_FUSION_DIR}/sli_fusion_wildfire_aoi.geojson':        {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_firesense_aoi.geojson':       {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_ard_acquisition_aoi.geojson': {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_bathymetry_aoi.geojson':      {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_surfacewater_aoi.geojson':    {'name_field': 'site_key'},
})
```

`site_key` in each GeoJSON equals the `Site Name abbrev` added in step 1, so
`create_sites_gdf_with_aois` matches each feature to its sheet row, **replaces the point
with the polygon, and preserves the row's attributes** (existing behavior, cell 17).

No change is needed in cell 17 — it already passes `multi_site_geojson_dict`,
`site_column='Site Name'`, `lat_column='Latitude'`, `lon_column='Longitude'`.

## 3. (Optional) verify centroids before pasting

Cell 14 already has the helper. Run it against the new dict to print centroid lat/lon
and confirm they match the sheet rows:

```python
siteslib.get_multi_site_centroids({
    f'{SLI_FUSION_DIR}/sli_fusion_wildfire_aoi.geojson':        {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_firesense_aoi.geojson':       {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_ard_acquisition_aoi.geojson': {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_bathymetry_aoi.geojson':      {'name_field': 'site_key'},
    f'{SLI_FUSION_DIR}/sli_fusion_surfacewater_aoi.geojson':    {'name_field': 'site_key'},
})
```

## 4. Regenerate — cell 17 then cell 37

Re-run cell 17 (builds `sites_evaluation_gdf`) and cell 37
(`sites_evaluation_gdf.to_file(eval_sites_aoi.geojson)`). Output grows from 622 to
**663** features (622 + 41).

## Schema additions — included (decision accepted 2026-11-05)

The doc (§7) requires AOI metadata the original 25-column sheet did not carry. These are
now **dedicated columns** in `new_eval_sites_rows.csv`, appended after the existing
schema (33 columns total), so you add 8 new columns to the "Evaluation Sites" tab when
pasting:

```
aoi_id, aoi_family, aoi_level, parent_aoi, event_id, ignition_datetime,
containment_datetime, geometry_version
```

- `aoi_level` = 1 for the ARD acquisition tiles (containers), 2 for fire/bathy/SWE AOIs.
- `parent_aoi` links a Level-2 perimeter to the Level-1 ARD tile that contains it
  (populated only where they actually nest — 3 of 21 perimeters; see data-model note).
- `notes` now carries only the residual fields without a dedicated column
  (`area_km2`, `gis_acres`, `role`, `bbox_wgs84`).

These extra columns are metadata only; the notebook wiring (keyed on `site_key`) is
unaffected.

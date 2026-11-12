# SPOT6 Cross-Site Contamination Bug Fix

## Executive Summary
Two SPOT6 acquisitions were incorrectly showing associations with both Albuquerque and Shadnagar sites after the `dissolve()` aggregation step. The root cause: **`link_acquisitions_to_sites()` was aggregating per-row site associations by `acquisition_id`, which broadcast combined site lists to all rows sharing the same ID.**

## The Bug

### What You Observed
After running:
```python
footprint_gdf_acquisitions = footprint_gdf.dissolve(by=['acquisition_id', 'metadata_path'], ...)
footprint_gdf_acquisitions_sites, acq_site_mapping = csdalib.link_acquisitions_to_sites(footprint_gdf_acquisitions, ...)
```

Two SPOT6 acquisition rows (`SEN_SPOT6_20260123_045336100_000` and `SEN_SPOT6_20260123_045437100_000`) were both showing:
- Site_Primary, Site_Secondary, Site_Tertiary containing both **Albuquerque** AND **Shadnagar**
- This is impossible because the acquisitions have different geometries at different locations

### Why It Happened
You already had the right instinct by adding `metadata_path` to the dissolve! This correctly kept the two SPOT6 acquisitions as **separate rows** with different geometries. However, `link_acquisitions_to_sites()` was then:

1. **Spatial join** creates per-row associations:
   - Row 0 (Albuquerque geom) → Site='Albuquerque'
   - Row 1 (Shadnagar geom) → Site='Shadnagar'

2. **Aggregation by acquisition_id** combines them:
   ```python
   acquisition_site_mapping = joined.groupby('acquisition_id')[site_name_col].apply(list)
   # Result: acquisition_id → ['Albuquerque', 'Shadnagar']
   ```

3. **Merge back on acquisition_id** broadcasts combined list to both rows:
   ```python
   footprint_with_sites = footprint_gdf.merge(acquisition_site_mapping, on='acquisition_id')
   # Both rows now have sites=['Albuquerque', 'Shadnagar'] ✗ WRONG
   ```

## The Fix

### Changes to `link_acquisitions_to_sites()`
The fix preserves **per-row site associations** instead of aggregating by `acquisition_id`:

```python
# BEFORE (aggregates by acquisition_id - combines sites for duplicate IDs)
acquisition_site_mapping = joined.groupby('acquisition_id')[site_name_col].apply(list)
footprint_with_sites = footprint_gdf.merge(acquisition_site_mapping, on='acquisition_id')

# AFTER (preserves per-row associations - each row keeps only its sites)
per_row_sites = joined.groupby(joined.index)[site_name_col].apply(list)  # Group by ROW INDEX not acquisition_id
footprint_with_sites = footprint_gdf.copy()
footprint_with_sites['sites'] = per_row_sites  # Each row gets ITS sites, not all sites for that ID
```

### What This Means
- **Row 0** (Albuquerque) → sites=['Albuquerque'] ✓ CORRECT
- **Row 1** (Shadnagar) → sites=['Shadnagar'] ✓ CORRECT
- No cross-site contamination, even if both rows share the same `acquisition_id`

## Testing the Fix

After deploying this fix, re-run your notebook:

```python
# 1. Process and dissolve as before
footprint_gdf_acquisitions = footprint_gdf.dissolve(by=['acquisition_id', 'metadata_path'], ...)

# 2. Link to sites (now uses fixed function)
footprint_gdf_acquisitions_sites, acq_site_mapping = csdalib.link_acquisitions_to_sites(
    footprint_gdf_acquisitions, 
    sites_gdf
)

# 3. Verify SPOT6 rows are now correct
spot6_rows = footprint_gdf_acquisitions_sites[
    footprint_gdf_acquisitions_sites['sensor'] == 'SPOT6'
]
print(spot6_rows[['acquisition_id', 'metadata_path', 'Site_Primary', 'num_sites']].to_string())

# Expected: Two separate rows with Site_Primary='Albuquerque' and 'Shadnagar' respectively
# NOT both showing both sites
```

## Root Cause of Duplicate acquisition_id (Still TODO)

The fact that you need to dissolve on `(acquisition_id, metadata_path)` indicates two different SPOT6 acquisitions are getting the **same** `acquisition_id` value. This is a deeper issue in the `derive_acquisition_id()` function that should be addressed separately:

- **Current**: Using `DATASET_NAME` from Airbus DIMAP, which can be shared across jobs
- **Better**: Use `JOB_ID` from `DELIVERY_IDENTIFICATION/JOB_ID` in the XML, which is unique per acquisition

See [SPOT6_DUPLICATE_ACQUISITION_ID_FIX.md](SPOT6_DUPLICATE_ACQUISITION_ID_FIX.md) for the long-term fix.

## Files Changed
- `lib/csdalib.py` - `link_acquisitions_to_sites()` function
  - Lines ~1035-1085: Changed aggregation logic to preserve per-row associations
  - Now uses `joined.index` instead of `'acquisition_id'` for grouping

## Summary
This is a **post-dissolution** fix that prevents the spatial join aggregation from contaminating rows with duplicate IDs. It allows your existing workaround (dissolving on `metadata_path`) to work correctly without cross-site contamination.

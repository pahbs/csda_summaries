# SPOT6 Duplicate Acquisition ID Bug: Root Cause & Solution

## Executive Summary
Two SPOT6 acquisitions are incorrectly reporting cross-site associations (Albuquerque & Shadnagar) due to a flaw in how acquisition IDs are generated and merged back to footprints. The bug occurs in **three layers**:

1. **sensor_profiles.py**: Acquisition ID is too coarse (DATASET_NAME only)
2. **csdalib.py process_files()**: Per-file footprints all share the same acquisition_id if from same job
3. **csdalib.py link_acquisitions_to_sites()**: Merge operation doesn't deduplicate on (acquisition_id, geometry) level

---

## Root Cause Analysis

### Layer 1: Airbus DIMAP Profile Configuration

**File:** `lib/sensor_profiles.py` (line ~678-700)

```python
'airbus_dimap': {
    'acquisition_id_field': 'catid',  # ← THIS FIELD IS THE BOTTLENECK
    ...
    'fields': {
        'catid': {'tag': 'SOURCE_ID', 'fallback_tags': ['DATASET_NAME']},
        ...
    }
}
```

**Problem:**
- For SPOT6, `SOURCE_ID` in the DIMAP metadata is often a reference source name (e.g., "R3D", "STRIP_DS_SPOT6_...")
- Fallback is `DATASET_NAME`, which extracts: `ORT_SPOT6_20250824_173052200_000`
- This DATASET_NAME is **shared across all scene tiles (R#C#) from the same job/acquisition**

**Example from your data:**
```
File 1: IMG_SPOT6_MS_202508241730512_ORT_7513478101_R1C1.TIF
File 2: IMG_SPOT6_MS_202508241730512_ORT_7513478101_R1C2.TIF  ← Same timestamp!
File 3: IMG_SPOT6_MS_202508241730512_ORT_7513478101_R2C1.TIF  ← Same timestamp!

All map to DATASET_NAME = ORT_SPOT6_20250824_173052200_000
All get acquisition_id = ORT_SPOT6_20250824_173052200_000  ← DUPLICATE!
```

### Layer 2: Per-File Processing (Process_files)

**File:** `lib/csdalib.py` (function `process_file()`)

The dispatcher correctly processes each file and assigns its `acquisition_id`. When a SPOT6 delivery has 4 scene tiles (R1C1, R1C2, R2C1, R2C2), the GeoDataFrame contains **4 rows with identical acquisition_id**:

```
footprint_gdf
  ├─ Row 0: acquisition_id='ORT_SPOT6_20250824_173052200_000', geometry=Albuquerque bounds
  ├─ Row 1: acquisition_id='ORT_SPOT6_20250824_173052200_000', geometry=Albuquerque bounds
  ├─ Row 2: acquisition_id='ORT_SPOT6_20250824_173052200_000', geometry=Albuquerque bounds
  └─ Row 3: acquisition_id='ORT_SPOT6_20250824_173052200_000', geometry=Albuquerque bounds
```

**This is expected per-file behavior** — `build_acquisition_summary()` is supposed to collapse these 4 into 1 union polygon.

### Layer 3: Spatial Join Merge Bug

**File:** `lib/csdalib.py` (function `link_acquisitions_to_sites()`, lines ~977–1100)

**Current code flow:**
```python
# Step 1: Spatial join
joined = gpd.sjoin(
    footprint_gdf,  # ← Input has duplicate acquisition_ids
    sites_buffered[[site_name_col, 'geometry']],
    how='inner',
    predicate='intersects'
)
# Result: ONE ROW per (acquisition_id, Site) pair
# If one acquisition_id spans 2 sites, you get 2 rows in `joined`

# Step 2: Aggregate by acquisition_id
acquisition_site_mapping = joined.groupby('acquisition_id')[site_name_col].apply(
    lambda x: sorted(list(x.unique()))
).reset_index()
# Result: acquisition_site_mapping has ONE row per UNIQUE acquisition_id

# Step 3: Merge back
footprint_with_sites = footprint_gdf.merge(
    acquisition_site_mapping[...],
    on='acquisition_id',
    how='left'
)
# BUG: If footprint_gdf has 4 rows with the same acquisition_id,
#      and acquisition_site_mapping lists [Albuquerque, Shadnagar],
#      ALL 4 rows get Site_Primary='Albuquerque' (alphabetically first)
#      But geometries span both sites!
```

**The explicit bug:**
```python
# Before merge:
footprint_gdf
  ├─ acquisition_id='ORT_SPOT6_...', geometry=Albuquerque_poly
  ├─ acquisition_id='ORT_SPOT6_...', geometry=Albuquerque_poly
  ├─ acquisition_id='ORT_SPOT6_...', geometry=Albuquerque_poly (actually overlaps Shadnagar!)
  └─ acquisition_id='ORT_SPOT6_...', geometry=Albuquerque_poly (actually overlaps Shadnagar!)

# acquisition_site_mapping:
#   acquisition_id='ORT_SPOT6_...', sites=[Albuquerque, Shadnagar]

# After merge:
footprint_with_sites  
  ├─ acquisition_id='ORT_SPOT6_...', Site_Primary='Albuquerque'  ✓
  ├─ acquisition_id='ORT_SPOT6_...', Site_Primary='Albuquerque'  ✓
  ├─ acquisition_id='ORT_SPOT6_...', Site_Primary='Albuquerque'  ✗ WRONG (overlaps Shadnagar!)
  └─ acquisition_id='ORT_SPOT6_...', Site_Primary='Albuquerque'  ✗ WRONG (overlaps Shadnagar!)
```

---

## Solution Options

### ✅ OPTION A: Fix Acquisition ID in sensor_profiles.py (BEST)

**Root fix**: Make acquisition_id truly unique per acquisition, not per file.

For Airbus SPOT6, use a combination that includes the actual raw strip or acquisition time:
- **Extract `INTERNAL_REFERENCE` or `JOB_ID`** instead of just `DATASET_NAME`
- Or **combine `DATASET_NAME` + scene tile info from filename**

**Implementation:**

In `sensor_profiles.py`, add to `airbus_dimap` profile:

```python
'extract_from_filename': {
    'dataset_basename': r'(DIM_.*?)(?:_R\d{1,2}C\d{1,2})?\.XML',  # extract DIM_ prefix
},
```

Then in `csdalib.py` `derive_acquisition_id()`, for Airbus, use `JOB_ID` (from metadata) or construct a composite:

```python
def derive_acquisition_id(record, profile):
    canonical_field = profile.get('acquisition_id_field')
    
    # For Airbus DIMAP: prefer JOB_ID, fall back to DATASET_NAME
    if profile_key == 'airbus_dimap':
        job_id = record.get('job_id')
        dataset_name = record.get('catid')  # This might be DATASET_NAME
        if job_id and str(job_id).strip():
            return str(job_id)  # Use JOB_ID as canonical ID
        elif dataset_name:
            return str(dataset_name)
    
    # ... rest of existing logic
```

**Pros:**
- Fixes the problem at the source
- Maintains semantic correctness (each true acquisition gets one ID)
- No downstream code changes needed

**Cons:**
- Requires updating metadata extraction in Airbus profile

---

### ✅ OPTION B: Deduplicate Before Linking (RECOMMENDED DEFENSIVE APPROACH)

**In the notebook**, ensure `build_acquisition_summary()` is called **before** `link_acquisitions_to_sites()`:

```python
# Current flow (BUGGY):
footprint_gdf = csdalib.process_files(files_to_process)
footprint_gdf_sites, acq_site_mapping = csdalib.link_acquisitions_to_sites(footprint_gdf, sites_gdf)

# FIXED flow:
footprint_gdf = csdalib.process_files(files_to_process)

# CRITICAL: Collapse per-file footprints to per-acquisition BEFORE spatial join
footprint_gdf_acquisitions = csdalib.build_acquisition_summary(footprint_gdf)

# Now link to sites (one row per acquisition, guaranteed)
footprint_gdf_sites, acq_site_mapping = csdalib.link_acquisitions_to_sites(
    footprint_gdf_acquisitions,  # ← Use acquisition-level, not file-level
    sites_gdf
)
```

**Why this works:**
- `build_acquisition_summary()` unions all scene tiles of the same acquisition into one polygon
- Result is **one row per unique acquisition_id**
- Spatial join then matches one acquisition geometry to sites (not multiple tile geometries)
- No ambiguity in site assignment

**Pros:**
- Simple one-line fix in notebook
- No changes to library code
- Semantically correct (acquisitions are spatially unioned)

**Cons:**
- Must be done at notebook call site
- User must remember to call it

---

### ✅ OPTION C: Deduplicate in link_acquisitions_to_sites()

**In `csdalib.py`**, add deduplication check before merge:

```python
def link_acquisitions_to_sites(...):
    # ... existing code up to spatial join ...
    
    joined = gpd.sjoin(
        footprint_gdf,
        sites_buffered[[site_name_col, 'geometry']],
        how='inner',
        predicate='intersects'
    )
    
    # DEFENSIVE: Deduplicate acquisition-site pairs to avoid inflating counts
    joined = joined.drop_duplicates(subset=['acquisition_id', site_name_col])
    
    acquisition_site_mapping = joined.groupby('acquisition_id')[site_name_col].apply(
        lambda x: sorted(list(x.unique()))
    ).reset_index()
    
    # ... rest of existing code ...
```

**Pros:**
- Prevents multiple scene tiles from the same acquisition from each contributing to site counts
- Defensive against duplicates

**Cons:**
- Doesn't fix the root problem (still leaves per-file rows in footprint_gdf)
- Only masks the symptom

---

### ✅ OPTION D: Add Validation & Error Detection

**In both `csdalib.py`**, add assertions to detect this bug early:

```python
def link_acquisitions_to_sites(...):
    # ... existing code ...
    
    # After merge, validate no duplicates
    n_duplicates = footprint_with_sites['acquisition_id'].duplicated().sum()
    if n_duplicates > 0:
        print(f"WARNING: {n_duplicates} duplicate acquisition_ids detected!")
        print("This may cause incorrect site associations.")
        duplicates_df = footprint_with_sites[footprint_with_sites['acquisition_id'].duplicated(keep=False)]
        print(f"Duplicates:\n{duplicates_df[['acquisition_id', 'Site_Primary', 'geometry']]}")
        raise ValueError(
            f"Found {n_duplicates} duplicate acquisition_ids. "
            "Call build_acquisition_summary() first to collapse per-file footprints."
        )
    
    return footprint_with_sites.to_crs(4326), acquisition_site_mapping
```

**Pros:**
- Catches the bug immediately
- Clearly directs user to the fix

**Cons:**
- Doesn't fix the problem, just detects it

---

## Recommended Implementation Path

### Step 1: Implement Option B (Immediate Fix)
Update your notebook to call `build_acquisition_summary()` before `link_acquisitions_to_sites()`.

### Step 2: Implement Option D (Defensive)
Add the validation assertion to `link_acquisitions_to_sites()` so users can't accidentally skip Step 1.

### Step 3: Implement Option A (Long-term Fix)
Update `sensor_profiles.py` to extract `JOB_ID` as the canonical acquisition ID for Airbus DIMAP.

---

## Testing the Fix

After implementing the fix, verify with:

```python
# Should return 2 different acquisition_ids
spot6_spot_dups = footprint_gdf[
    footprint_gdf['sensor'] == 'SPOT6'
].groupby('acquisition_id').size()

spot6_spot_dups[spot6_spot_dups > 1]  # Should be EMPTY

# Check that Albuquerque and Shadnagar are NOT in the same acquisition
albuquerque_spots = footprint_gdf[footprint_gdf['Site_Primary'] == 'Albuquerque']
shadnagar_spots = footprint_gdf[footprint_gdf['Site_Primary'] == 'Shadnagar']

for acq_id in albuquerque_spots['acquisition_id']:
    assert acq_id not in shadnagar_spots['acquisition_id'].values, \
        f"Acquisition {acq_id} spans both sites!"

print("✓ No cross-site acquisition contamination detected")
```

---

## Files to Review/Modify

| File | Change | Priority |
|------|--------|----------|
| `notebooks/footprint_CSDA_eval_refactored.ipynb` | Insert `build_acquisition_summary()` call before `link_acquisitions_to_sites()` | **HIGH** |
| `lib/csdalib.py` `link_acquisitions_to_sites()` | Add validation assertion | **MEDIUM** |
| `lib/sensor_profiles.py` `airbus_dimap` | Update to use JOB_ID as canonical acquisition_id | **LOW** |

---

## Summary Table

| Problem | Symptom | Root Cause | Solution |
|---------|---------|-----------|----------|
| Duplicate acquisition_id for SPOT6 | Multiple scene tiles share same ID | DATASET_NAME used as ID; doesn't differentiate tiles | Use JOB_ID instead (Option A) |
| Cross-site contamination | Albuquerque & Shadnagar in same row | Merge doesn't deduplicate per-file rows | Call `build_acquisition_summary()` first (Option B) |
| Silent data corruption | Results look correct but are wrong | No validation in merge logic | Add assertions (Option D) |

# Data-model recommendation — integrating SLI-FUSION AOIs

> **Decisions accepted 2026-11-05.** (1) Add the §7 metadata columns — the 41 paste-ready
> rows now carry 8 dedicated columns appended after the 25-col schema: `aoi_id, aoi_family,
> aoi_level, parent_aoi, event_id, ignition_datetime, containment_datetime,
> geometry_version` (`notes` keeps only `area_km2 / gis_acres / role / bbox_wgs84`).
> (2) Model the hierarchy with `aoi_level` + `parent_aoi` (option a, flat); **flag the sparse
> ARD↔fire overlap to the USGS/SLI team.** (3) Keep both — new demo AOIs added, existing
> validation-site geometry untouched.


## The problem the new data exposes

The evaluation-site database is a **flat, Site-Name-keyed table** (one row per site,
point lat/lon, optional custom AOI geometry). The SLI-FUSION material is **hierarchical
and event-driven**:

- **Two AOI levels** (doc §8.5): Level-1 USGS ARD acquisition tiles (~22,500 km²
  containers) that *contain* Level-2 fire perimeters. These must be *linked, not merged*.
- **Name collisions**: Grasshopper, Little Giant, and Widemouth 2 each appear in both
  the wildfire-demo family and the FireSense family — the same fire, two campaigns.
- **Required metadata** (doc §7) absent from the 25-column schema: `aoi_id`, `event_id`,
  `ignition_datetime`, `containment_datetime`, `acquisition_window`, `product_objective`,
  `provider_product`, `geometry_version`.

## Recommendation (3 parts)

### 1. Keep the Google Sheet as the single source of truth; add a namespaced key column
Do **not** switch the master to the geojson (it is regenerated output). Instead:
- Treat **`Site Name abbrev` as the stable, namespaced primary key** (it already
  overrides `Site Name` in `read_from_sheet`). Namespace by family:
  `fire_<slug>_2026`, `firesense_<slug>_2026`, ARD tile label (`CU_h003v009`),
  `bathy_<slug>_2026`, `swe_<slug>_2026`. This resolves all collisions with zero
  ambiguity (verified: 0 collisions among the 41 new rows).
- Add a `Program Use = SLI-FUSION` value to separate this initiative from the existing
  `CSDA` (165) and `SLI` (444) rows without disturbing the corner-reflector/CSDA path.

### 2. Add the doc-required AOI metadata as real columns (not just `notes`)
Add seven columns so the AOI register is query-able and matches the doc's deliverable
spec: `aoi_id, aoi_family, aoi_level, event_id, ignition_datetime,
containment_datetime, geometry_version`. The staged GeoJSONs already carry these; until
the columns exist they are also mirrored into `notes` so nothing is lost.

### 3. Model the Level-1 / Level-2 hierarchy with a lightweight link, not nesting
The flat sheet cannot express containment. Two low-cost options — **recommend (a)**:
- **(a) `aoi_level` + `parent_aoi` columns.** ARD tiles are `aoi_level=1`,
  `parent_aoi` empty; fire perimeters are `aoi_level=2` with `parent_aoi` set to the
  ARD tile they fall in (computable by spatial join — see note below). Stays flat,
  one table, trivially filterable.
- (b) A second "ARD Acquisition Areas" sheet/tab, joined on `parent_aoi`. More faithful
  but adds a table to maintain. Defer unless the register grows.

> The 11 ARD tiles are **acquisition footprints, not evaluation targets**. They are
> included as `Priority Level = medium`, `Surface Domain = Land`, and flagged
> `aoi_level=1` so they can be filtered out of per-site evaluation summaries while still
> driving SDX archive/coverage queries.

> **Finding — the two levels barely overlap in this package.** A spatial join shows only
> **2 of 12** wildfire-demo perimeters (Kaiser Canyon, Little Giant) and **1 of 9**
> FireSense perimeters (Little Giant) fall inside the 11 provided ARD tiles. The tiles
> are a sparse, nationally distributed set (Alaska ×2, Hawaii ×1, scattered CONUS) rather
> than tiles selected to cover these specific 2026 fires. So `parent_aoi` is populated for
> only those few; for the rest the Level-1↔Level-2 link is currently empty. Worth raising
> with the USGS/SLI team: either the acquisition tiles or the fire set will need to grow
> for the two-level framework to actually nest.

## Reconciliation decisions (non-destructive default applied)

The bathymetry/surface-water families overlap existing validation sites. I did **not**
overwrite existing geometry. New demonstration AOIs were added as separate rows that
cross-reference the existing site in `notes`/`role`:

| New demo AOI | Existing site (kept as-is) |
|---|---|
| `bathy_apra_harbor_guam_2026` | `SDB_Guam` (point, custom AOI) |
| `bathy_florida_keys_2026` | `SDB_Florida_KeyWest` |
| `bathy_sw_puerto_rico_2026` | `SDB_PuertoRico` |
| `bathy_louisiana_gulf_2026` | *(new; near but distinct from `Lake Pontchartrain Causeway`)* |

- **Chesapeake Bay** bathymetry and **Alaska Coastal** bathymetry: doc gives no bbox →
  not staged; existing `Chesapeake_Bay` point retained.
- **Amazon** surface water: doc gives no bbox → existing `Amazon` (SAR) point retained.

**Decision for you:** keep these as separate demo-footprint rows (current default), or
*replace* the small validation-site geometry with the larger demo bbox. I recommend
keeping both — the small SDB sites are the validation anchors; the bboxes are acquisition
footprints with a different purpose.

## Optional: auto-compute `parent_aoi`

```python
import geopandas as gpd
ard = gpd.read_file('sli_fusion_ard_acquisition_aoi.geojson')[['site_key','geometry']]
l2  = gpd.read_file('sli_fusion_wildfire_aoi.geojson')      # + firesense
j = gpd.sjoin(l2, ard.rename(columns={'site_key':'parent_aoi'}),
              how='left', predicate='intersects')[['site_key','parent_aoi']]
```

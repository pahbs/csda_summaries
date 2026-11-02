# csda_summaries: activity log

What was done, decided or found in this repo, grouped by area. **Newest entries at the top**, both in "Recent activity"
and within each area. Add new work as a one-line item in Recent activity and as a dated entry in its area (top of the
area). Committed work: see `git log`; this log also covers uncommitted work, decisions and open issues.

**Areas**
1. [Multistac: unified search library](#1--multistac-unified-search-library): `lib/multistac*.py`, `lib/stac_providers.yaml`,
   `lib/stac_auth.py`, `lib/sensor_catalog.yaml`, `tests/smoke_multistac.py`
2. [Archive analyses: site and global](#2--archive-analyses-site-and-global): `notebooks/multistac_site_analysis.ipynb`,
   `multistac_global_analysis.ipynb`, `multistac_search_tutorial.ipynb`, older `csda_stac_search*.ipynb`
3. [Data requests and downloads](#3--data-requests-and-downloads): CSDA download API, Earthdata / S3, vendor requests
4. [Sites and AOIs](#4--sites-and-aois): `sites/*.geojson`, `lib/siteslib.py`, AOI maps
5. [Footprints and acquisition summaries](#5--footprints-and-acquisition-summaries): `lib/csdalib*.py`, `lib/sensor_profiles.py`
6. [Evaluation results, RadCalNet and spectral response](#6--evaluation-results-radcalnet-and-spectral-response)
7. [Repository and docs](#7--repository-and-docs)

---

## Current status (15 Oct 2026)

- **Multistac** searches CSDA STAC, Earthdata CMR (CSDA provider), Satellogic and now **Hydrosat** with one call and one
  table. Satlantis and ImageSat to be added when access exists. CSDA STAC has no item counts; CSDA has been asked to add them.
- **Global search** (`multistac_global_analysis.ipynb`, run under nohup on forest203 since 14 Oct, log
  `/explore/nobackup/people/pmontesa/multistac/global_analysis/search_forest203.log`): 40 % of 4,359 month-searches after
  22 h. **CSDA Planet months take 6–14 h each** and dominate; exclude Planet or sample it (`MAX_ITEMS_PER_MONTH`) to finish.
- **Large amount of uncommitted work**: multistac changes since the 12 Oct commit, Hydrosat, many notebooks and site files
  (`git status`). Decide what to commit vs keep local (e.g. `notebooks/s3_tmp_credentials.json` must never be committed).

---

## Recent activity (all areas)

- 2026-11-02 · [6] Timeline joint events: CSDA Evaluation Results dB (Jul 2026, ongoing) and the planned sharing of the joint evaluation comparison sheet with ESA & USGS (placeholder 30 Nov); both link to the CSDA Evaluation Results slides.
- 2026-11-02 · [6] Timeline: OroraTech, Orbital Sidekick, ImageSat and Satlantis added as evaluations (own panels), each with its TEM: OroraTech 25 Aug, Orbital Sidekick 16 Oct, ImageSat 22 Oct, Satlantis 2 Nov 2026; Airbus 24 Sep TEM relabeled.
- 2026-11-02 · [6] Timeline: Satellogic v2 plan: confirm STAC API search type with vendor and build the geometric/radiometric site list (2-6 Nov), request v2 archive data at the sites (9-20 Nov); initial STAC analysis notebook milestone (27 Oct).
- 2026-11-01 · [3][6] Vantor's archive vs CSDA since the 14 Sep Legion request: Vantor collected 55 Legion images at the 9 sites, only 19 in CSDA (36 not delivered, 9 of them meeting the request); new section 8 of `vantor_legion_supp_tracking.ipynb` writes the timeline notes.
- 2026-11-01 · [6][4] Timeline: joint event "ESA site list confirmed" (24 Sep 2026): the `ESA_misc_20260924` tab of the site request sheet (14 sites) is the reference site list for all vendors going forward.
- 2026-11-01 · [6] Timeline: Vantor-Legion notes rewritten in plain language with the 1 Nov status (18 supplemental images arrived; 23 of 65 Legion images meet the request).
- 2026-11-01 · [3][1] `vantor_legion_supp_tracking.ipynb` rebuilt: tracks all 9 sites against the sheet's `Legion_20260914` tab plus the supplemental windows; CSDA `maxar-legion` cloud cover fixed (0-1 fraction, now scaled to percent).
- 2026-10-30 · [6] Timeline: Satellogic added as a 4th evaluation (v2 evaluation from STAC API access, ~6 Oct, end TBD); HydroSat STAC API access (15 Oct); Airbus / Vantor data status; interactive HTML timeline on GitHub Pages.
- 2026-10-28 · [1] Satellogic field comparison: `quickview-visual-thumb` = 1 item per capture with the true footprint but no `view:azimuth` / `view:incidence_angle`; `quickview-visual` tiles have them; neither gives native GSD.
- 2026-10-23 · [1][3] pandas 2 (ILAB DEV kernel) datetime bug: mixed ISO formats became NaT, so CSDA items without fractional seconds dropped out of searches/heatmaps (20 of 236 in a test) and the order-tracking download cell failed; fixed.
- 2026-10-23 · [3] `airbus_order_tracking.ipynb`: newly arrived tasked acquisitions (fresh search since 1 Aug 2026) fill the sheet's New Tasking Submitted slots (15 slots, 11 acquisitions); download skips products already on disk.
- 2026-10-23 · [5] Skyplot geometry fixed for Airbus (and Satellogic elevation): incidence was stored as satellite elevation; Pleiades 1A/1B AZIMUTH_ANGLE is the along-track direction, not the satellite azimuth.
- 2026-10-23 · [5] Footprint notebook now lists duplicate deliveries and has month heatmaps; Airbus augmentation: 81 of 83 acquisitions new, 4 products (2 SPOT6 scenes) duplicate `Airbus/SPOT`.
- 2026-10-16 · [3] New `csda_stac_download_planet_ids.ipynb`: download CSDA items by STAC id (19 Planet PSScene, Railroad Valley, Jun–Jul 2024) via `multistac_download`.
- 2026-10-15 · [1][2] Vendor-only searches: `CSDA_INCLUDE = []` now skips CSDA (empty list = skip provider); site analysis notebook works for Satellogic only.
- 2026-10-15 · [1] Satellogic: 'quickview' is a processing level (L1B, ~70–78 cm), not a collection; our archive STAC is Aleph v2 archive discovery; 1 capture = many 2 km tiles.
- 2026-10-15 · [1] Satellogic: `quickview` is not a collection (only `quickview-visual`, `quickview-visual-thumb`); search now warns on unknown collection IDs.
- 2026-10-15 · [1] Tutorial notebook: HTTP 415 on Hydrosat token in an already-running kernel (stale `stac_auth`); first cell now reloads it.
- 2026-10-15 · [1] Hydrosat enabled in multistac with the new API client credentials; search tested (0 failures).
- 2026-10-14 · [2] Counting units clarified: products vs acquisitions in heatmaps and skyplots; Legion slides for a colleague.
- 2026-10-14 · [2] Global search moved to a nohup background run on forest203.
- 2026-10-14 · [1] Spectral mode (pan / ms / pansharpened) separated per product across vendors; overlapping sites handled.
- 2026-10-14 · [2] Density maps: Legion at sites not showing fixed; INCLUDE list for CSDA collections.
- 2026-10-13 · [4] Leetown Science Campus (USGS) added to sites.
- 2026-10-12 · [3] WorldView request notebook for DART simulations (CMR search, Cognito/MFA S3 download).
- 2026-10-12 · [1] Multistac committed (`cbc5695`): CSDA STAC + CMR + Satellogic, plots, downloads, notebooks, tests.
- 2026-10-11 · [1] Earthdata CMR backend (`csda-cmr`), catalog overview tables, timeline heatmap, display names, skyplots.
- 2026-10-11 · [1] Multistac plan and phases 1–4 (`MULTI_STAC_SEARCH_PLAN.md`).
- 2026-10-02 · [2] CSDA STAC search tutorial notebook.
- 2026-09-30 · [4] Gobabeb TIR site size edited; HydroSat request AOIs (Kerry) through 2 Oct.
- 2026-09-30 · [2] Distributed global CSDA search script (`run_distributed_global_search.sh`).
- 2026-09-25 · [4] HLS golden tiles GeoJSON.
- 2026-09-24 · [6] Timeline notebook; [4] two ESA sites (Leo) added to AOI maps.
- 2026-09-22 · [4] Request AOIs: Airbus, OroraTech, Vantor Legion, HydroSat OR2.

---

## 1 · Multistac: unified search library

Goal: one search call and one normalized table across every catalog with access (STAC and CMR), with breakdowns by
affiliation (data owner; Maxar = Vantor), constellation and sensor. New vendors are a YAML profile (plus an auth plugin
only if needed), never a separate search API.

### 2026-10-28 · Satellogic: `quickview-visual-thumb` vs `quickview-visual` fields
- Same acquisition, two products: `quickview-visual-thumb` is one 20 m image of the whole capture; `quickview-visual`
  is that capture cut into full-resolution UTM grid tiles. Thumb fields are a subset of tile fields (none unique to the
  thumb); tiles add 4. Many shared fields hold different values because they describe a different image. Satellogic
  does not document why the thumb lacks those 4.
- Compared live items for one capture (San Diego, 2026-09-22, SN45, outcome `cd2fbb90-40c6-4948-a833-4e0d5fb9bfb4`):
  1 thumb vs 70 tiles. Thumb footprint lies within the tiles' bounds; tile union is larger (~280 vs ~201 km²) because
  square cells overshoot the strip edges.

| Field | Thumb (`quickview-visual-thumb`) | Tiles (`quickview-visual`) | What the value describes |
|---|---|---|---|
| **Item count** | 1 per capture | Many per capture (70 here) | |
| **geometry** | Whole capture footprint | One grid square | Thumb is the true acquisition extent |
| `satl:outcome_id` | ✓ same | ✓ same | Capture ID, used for ordering |
| `satl:transaction_id` | ✓ same | ✓ same | Capture |
| `satl:product_version` | ✓ same | ✓ same | Processing version |
| `platform` | ✓ same | ✓ same | Satellite (newsat45) |
| `satl:satellite_generation` | ✓ same | ✓ same | MarkV |
| `satl:ground_lock` | ✓ same | ✓ same | Capture |
| `satl:product_name` | QUICKVIEW_VISUAL_THUMBNAIL | QUICKVIEW_VISUAL | Product type |
| `datetime` | Capture start | Each tile's own time | |
| `view:off_nadir` | ✓ 24.79 | ✓ 24.78–24.81 | Almost constant, so the thumb value is fine |
| `view:sun_elevation` / `view:sun_azimuth` | ✓ | ✓ nearly the same | Thumb value is fine |
| `eo:cloud_cover` | Whole capture (11.7) | That tile only (0–55) | |
| `satl:valid_pixel` | Whole capture | That tile only | |
| `satl:haze_cover` | Whole capture | That tile only | |
| `satl:geoaccuracy_*` (12 fields) | One value, likely measured on the 20 m image | Per tile | Not comparable across the two |
| `satl:ba_*` band alignment (12 fields) | One value, likely measured on the 20 m image | Per tile | Not comparable across the two |
| `gsd` | 20 (thumbnail pixel) | 0.86 (QuickView pixel) | **Neither is the native GSD** |
| `proj:epsg` | 3857 (Web Mercator) | 32611 (UTM 11N) | Each item's own raster |
| `proj:shape` / `proj:transform` | Thumbnail raster | Tile raster | Each item's own raster |
| `view:azimuth` | ❌ missing | ✓ | Satellite look direction |
| `view:incidence_angle` | ❌ missing | ✓ | Viewing angle at the ground |
| `grid:code` | ❌ missing | ✓ (e.g. `11N_494_3606`) | Tile ID |
| `satl:last_modified` | ❌ missing | ✓ | Tile update time |
| **Assets** | analytic, cloud, preview, thumbnail | analytic, cloud, preview, thumbnail | Same names, different images |

- In short: the thumb gives the correct extent plus capture-level identity, cloud and sun/off-nadir fields. The tiles
  are the only source of `view:azimuth` and `view:incidence_angle`. Neither gives the true GSD.
- Without `view:incidence_angle`, multistac derives `sat_elevation` from `view:off_nadir` (`_satellite_position`,
  flagged in `sat_elevation_source`); `sat_azimuth` cannot be derived from the thumb.
- Decision pending: make `quickview-visual-thumb` the Satellogic default collection, optionally fetching one tile per
  `satl:outcome_id` to fill `view:azimuth` / `view:incidence_angle`.

### 2026-10-23 · Mixed ISO datetimes under pandas 2 (`multistac._to_utc`)
- `pd.to_datetime(..., utc=True, errors="coerce")` in pandas >= 2 takes one format from the first value; CSDA STAC has
  both `2026-10-13T04:35:47Z` and `...47.100Z`, so the other format silently became NaT. In the DEV kernel (pandas
  2.2.3) 20 of 236 Airbus items lost their datetime and `by_month` / heatmaps undercounted; `month_table` on the local
  footprints counted 348 of 532 acquisitions. TensorFlow kernel (pandas 1.5.3) was not affected.
- `multistac._to_utc` (format="ISO8601" on pandas >= 2) now used for search results, `month_table`, `overview`
  first/last and pass grouping. Checked in both kernels: 0 NaT, 532 / 532, smoke test OK.
- `airbus_order_tracking.ipynb` download cell: the footprint fallback time is parsed per value (it raised under pandas 2).

### 2026-10-15 · Empty collection list skips a provider (vendor-only searches)
- Before: a provider given `[]` fell back to its `default_collections` (e.g. CSDA → satellogic, planet, airbus-optical,
  maxar-legion), so `CSDA_INCLUDE = []` silently still searched CSDA. Now `None` = defaults, `[]` = skip
  (`multistac._provider_collections`, used by `search` and `overview`).
- Satellogic-only site search tested (3 evaluation sites, June 2025): only Satellogic rows; PICS Libya-4 18 tiles from 6
  acquisitions, Belo Horizonte 12 from 2; one failed task (intermittent Satellogic 502), retried on re-run.

### 2026-10-15 · Satellogic: what "quickview" and the Orders / Archive API mean for our search
- Satellogic (email): "quickview" is an older term for a **processing level** (L1B at ~70 cm), not a collection; they
  suggested the Aleph v2 "Orders API" to search archive captures and their metadata without downloading.
- Checked (docs + API with our credentials): Aleph v2's "STAC-compliant archive discovery" **is** the endpoint our profile
  already uses, `https://api.satellogic.com/v2/archive` (landing page lists `/collections`, `/search`, `/queryables`,
  `/docs`, `/openapi.json`; collections `quickview-visual`, `quickview-visual-thumb`). The other v2 endpoints
  (`/v2/orders`, `/v2/captures`, `/v2/deliverables`) are for ordering, tasking and deliveries, not archive search.
  Archive orders use SKU `ARCIMG-…` with `outcome_id` and `processing_level` (e.g. L1C, L1D, L1D_SR).
- Metadata is not truncated: items carry `satl:product_name` QUICKVIEW_VISUAL, gsd 0.78 m, platform (e.g. newsat26,
  MarkV), off-nadir, incidence, sun angles, cloud and haze cover, `satl:outcome_id`, product version, geoaccuracy.
- **One capture = many 2 km grid tiles** (`grid:code` SATL-2KM-…; 42 tiles for one example outcome_id). Products are
  tiles; acquisitions (= captures) come from `satl:outcome_id`, already the profile's acquisition rule. Report Satellogic
  counts as acquisitions.
- Open question for Satellogic: whether search can show which processing levels (L1C / L1D / L1D_SR) exist for a
  capture before ordering, or whether every archive capture can be ordered at every level.

### 2026-10-15 · Unknown collection IDs now warn (Satellogic `quickview`)
- `quickview-visual` is only the Satellogic profile default (used when the notebook passes `None`); a list in
  `PROVIDERS` overrides it. Satellogic's archive exposes two collections to this account: `quickview-visual` and
  `quickview-visual-thumb`. A search on `quickview` returned 0 items with no error.
- `multistac.search` now checks explicit collection IDs against the provider's list and warns, naming the available ones.
- Test (evaluation sites, June 2025): `quickview-visual` 5,373 items, `quickview-visual-thumb` 858; one HTTP 502 from
  Satellogic's server, logged as a failed task (rerun resumes from the cache).
- `lib/staclib.py` (older code) still hard-codes `collections=['quickview-visual']` in its Satellogic search.

### 2026-10-15 · Hydrosat enabled
- New credentials in `credentials.ini`: `[Hydrosat_STAC_API]` (client_id / client_secret) and `[Hydrosat_login]`
  (username / password). **The STAC API needs the client credentials** (OAuth2 client credentials; token from
  `https://auth.hydrosat.com/oauth2/token`, form-encoded request, ~1 h tokens). The username / password returns 401 on the
  STAC API (likely for the Discovery Portal). Source: https://satdocs.hydrosat.com/api-reference-and-specification/authentication
- `lib/stac_auth.py`: `OAuth2ClientCredentials` takes `token_request: form` (default JSON, unchanged for other providers).
- `lib/stac_providers.yaml` (hydrosat): enabled; real token URL; `default_collections: [vz-l1b, vz-l2]`;
  `acquisition_id` from `hydrosat:scene_id`, so the L1B and L2 items of one scene count as one acquisition.
- Collections: `vz-viri-l1a`, `vz-liri-l1a`, `vz-liri-l1a-night`, `vz-l1b`, `vz-l1b-night`, `vz-l2`; ~140,000 items each
  in L1B and L2, Feb 2025 to now. Items map cleanly: platform `vanzyl-01` → Hydrosat / VanZyl / VZ01 (sensor catalog
  rule already present), `instruments` liri + viri → spectral mode `ms+tir`, view angles, cloud cover.
- Test (CSDA sites, Jun–Sep 2025, TensorFlow env): 456 searches, 0 failed; 106 items = 53 acquisitions at 80 site
  matches. Not yet checked: `in_csda` matching against CSDA's own Hydrosat holdings. Full COG download needs ordered data.
- Gotcha: in a kernel started before an auth change, `importlib.reload(multistac)` does not reload `stac_auth`; the
  token request then went out as JSON and Hydrosat answered **HTTP 415**. Restart the kernel, or reload `stac_auth` first
  (now in the tutorial's first cell).

### 2026-10-14 · Products vs acquisitions; spectral modes; overlapping sites
- Counts were mixing **products** (catalog items: pan, MS, pansharpened, processing levels) and **acquisitions** (one
  collect). `month_table` / `plot_month_heatmap` take `count="products" | "acquisitions"`; skyplots show
  n = acquisitions plus number of product types. Notebooks state which unit each count uses.
- Spectral mode separated per product across vendors via profile rules (`spectral_mode`), and `acquisition_id` rules per
  vendor (Legion: products within 120 s of one pass; Airbus and BlackSky from ID patterns; Satellogic from outcome ID).
- Overlapping sites (e.g. WLEF and its sky-camera sites) double-counted items: counts can be unique per item or per site.

### 2026-10-12 · First commit (`cbc5695`)
- Provider profiles (YAML, display names), auth plugins, normalized output (affiliation / constellation / sensor via
  `sensor_catalog.yaml`; sun and satellite geometry for skyplots), `in_csda` holdings flag, server + client filters,
  resumable cache, site and global (month-split) searches. Backends: STAC and NASA CMR. Downloads via the CSDA download
  API and Earthdata HTTPS. Hydrosat disabled pending API access.

### 2026-10-11 · CMR backend, overview tables, timeline heatmap, skyplots
- Earthdata access is through the **CMR search API** (not STAC): provider `csda-cmr`, all CSDA collections with granules.
- Catalog overview table at the top of each search (collection, first / last date, total) and totals by year and month;
  timeline heatmap with date-range bands for collections without counts.
- Display names: `CSDA STAC`, `Earthdata CMR – CSDA`, `Satellogic`. Skyplots from sun / sensor geometry (vendor-specific
  angle mapping; azimuth convention per vendor still unverified).
- Decision: **do not count items client-side** for CSDA STAC; CSDA asked to provide counts.
- `MULTI_STAC_SEARCH_PLAN.md`: phases 1–4 for CSDA and Satellogic (`stac_providers.yaml`, `stac_auth.py`,
  `multistac.py`, smoke tests, tutorial).

---

## 2 · Archive analyses: site and global

### 2026-10-15 · `multistac_site_analysis.ipynb` usable for one vendor only
- Parameters for Satellogic only: `CSDA_INCLUDE = []`, `EXTRA_PROVIDERS = {'satellogic': ['quickview-visual']}`.
- Cells made provider-agnostic: distributions fall back from `csda:item_type` to `collection`; the footprint map falls
  back to the site with most results when the chosen `SITE` has none.

### 2026-10-14 · Global search in background on forest203
- `multistac_global_analysis.ipynb` searches did not complete interactively; run under nohup on forest203 (log above).
  Status 15 Oct: 40 % after 22 h; CSDA Planet months 6–14 h each. Next: exclude Planet or sample it.

### 2026-10-14 · Legion at our sites: slides and counting units
- Google Slides deck from `multistac_site_analysis.ipynb` for a colleague: where Legion data exist at our sites, using
  the notebook's plots and "acquisitions" (not "passes"); heatmap map added; sans-serif fonts.
- Heatmap n vs month-heatmap n differed (207 vs 125): products vs acquisitions and overlapping sites (see area 1).
- Density maps: Legion results not appearing at any grid size fixed; `CSDA_INCLUDE` list added; site selection no longer
  assumes every input site is in the results.

### 2026-10-02 · CSDA STAC search tutorial notebook (`6ad2d6f`)

### 2026-09-30 · Distributed global CSDA search
- `run_distributed_global_search.sh`: splits the world into longitude bands across nodes, `searchlib` logic per band.

### 2026-03 to 2026-07 · CSDA STAC searches (staclib)
- `staclib.py` searches, seasonal search by months (Jul), Legion example (Mar–Jun), multiple-collection examples.

---

## 3 · Data requests and downloads

### 2026-11-01 · Vantor Legion request tracking (`vantor_legion_supp_tracking.ipynb`, `lib/order_tracking.py`)
- Requirements read live from the request sheet's `Legion_20260914` tab (CSV export by gid 226856298;
  `google_sheet_csv_url`, `read_legion_request`). Export by tab name is unsafe: gviz returns the first tab if the
  name does not match.
- All 9 sites, fresh CSDA search from 2024-01-01; each acquisition checked for view angle (off-nadir <= sheet max),
  MS product and scene cloud cover (above the AOI limit = "check AOI", not fail). TOA vs SR cannot be checked (no
  CSDA field). Counts split into archive vs new since the 14 Sep 2026 request; ADAPT match within 120 s.
- 1 Nov: 65 acquisitions at 7 sites, 23 meet the request. Meets min: Libya-4 (also ideal), Valencia. Short: Golmud,
  Gobabeb, Baotou (1 of 6 sensors), Railroad Valley, WLEF. None: La Crau, Sioux Falls. Main failure: view angle
  (35 of 65; most Legion collects 11-20 deg off-nadir, request max 10 deg); Baotou mostly pansharpened only.
- Supplemental windows: 18 acquisitions (9 of 15 windows per site, 19 Sep - 26 Oct), above the supp tab's min 5;
  only 3 (Valencia) within 10 deg. None on ADAPT. The 30 Oct run returned 0 for the same search; unclear whether
  late delivery or a CSDA server problem that day.
- Section 8 (added later the same day): Legion collects in **Vantor's own archive** (Discovery API, lg01-lg06) since
  the request date, same requirement checks (`check_requirements`), matched to CSDA by site and sensor within 120 s.
  1 Nov: Vantor 55, in CSDA 19, **36 not delivered** (WLEF 14, Valencia 13, Libya-4 4, La Crau 2, Railroad Valley 2,
  Golmud 1); 13 meet the request, 9 of those not in CSDA (incl. the only La Crau and Railroad Valley ones). Since the
  first supplemental window (17 Sep): Vantor WLEF 23 / Valencia 22 vs 9 each in CSDA. The last cell prints the
  plain-language notes for `timeline.ipynb`.
- Monthly acquisition heatmaps per site (`multistac_plots.plot_month_heatmap`): all CSDA Legion acquisitions (section 3)
  and those meeting the requirements (section 4; 23 at 5 sites), same months on both. `CLOUD_COVER_MAX` (default None)
  is now passed to both searches.
- Open: request tab says min 3 at WLEF/Valencia, supp tab says min 5. Confirm whether `max_view_angle` means off-nadir
  (used) or incidence.
- multistac: CSDA `maxar-legion` `eo:cloud_cover` is a 0-1 fraction (checked against Vantor's percent for the same
  strips); new per-collection `cloud_cover_scale` in `stac_providers.yaml` (x100), also applied to the server-side
  cloud filter. `_per_collection` moved to the `Provider` base class.

### 2026-10-23 · New tasking received in `airbus_order_tracking.ipynb` (+ `lib/order_tracking.py`)
- Section 2b: fresh (uncached) CSDA search from `TASKING_SINCE` (2026-08-01) at the sites with *New Tasking
  Submitted* slots (Baotou, Golmud, Valencia, WLEF), appended to `res`.
- Section 3b: acquisitions since `TASKING_SINCE` not matched to an archive cell fill that site/platform's slots in
  Acq # order, oldest first; a TOA/SR slot only if CSDA has that radiometry. 23 Oct: 11 acquisitions (5 Oct - 21 Oct
  2026, mostly PNEO3) fill 15 slots; 78 slots still waiting; none without a slot.
- `write_csda_status` fills those cells with the sheet's own *New Tasking Received* legend colour and writes the CSDA
  acquisition ID (`PNEO3_202610061657285`; PNeo TOA also the ISO date). `read_airbus_tracking` now accepts these IDs,
  so the updated sheet reads back with tracking_id and acq_time (checked: 15 cells, IDs and times as assigned).
- Download: skip a product if `<item id>/` exists in `Data/Airbus` **or `augmentation`** (the old check missed the
  augmentation folder), or the same product is in the local footprints (platform, P/MS, radiometry, time from the
  metadata file name within 5 s; PMS HD products not taken for MS). 23 Oct: 174 already downloaded, 30 new (46.5 GB).
- Open: the sheet gets CSDA IDs, not the vendor DS_/ACQ_ IDs (those are in the DIMAP after download).

### 2026-10-16 · Download by item id (`csda_stac_download_planet_ids.ipynb`)
- Reads each item directly from CSDA STAC (`/collections/planet/items/<id>`), no search, then downloads with
  `multistac_download.download` (CSDA download API, Earthdata login from `[EarthData]`). Dry-run plan first; re-running resumes.
- First list: 19 Planet `PSScene` scenes, 4 Jun – 30 Jul 2024, all over Railroad Valley, NV (RadCalNet); all 19 found,
  11 assets each (basic/ortho analytic 8b, SR, UDM2, visual, XML, RPC, JSON, thumbnail) = 209 files.
  Output `/explore/nobackup/projects/CSDA_eval/csda_download/planet_railroad_valley_2024/csda/planet/<id>/`.
- Not yet downloaded (dry run only, from ADAPT). The thumbnail asset saves as `thumb` (no extension).

### 2026-10-12 · WorldView imagery for DART simulations (`629e19c`)
- Notebook (`multistac_wv_request.ipynb`) using multistac on Earthdata CMR only with `sites/WV_request_AOIs.zip`
  (e.g. SERC leaf-on WV-2/3 scene closest to 30 Jul – 4 Aug).
- Downloads authenticate as in `earthdata_s3_access_test.ipynb` (CSDA Cognito with MFA); S3 access needs a cloud
  platform. Downloads that worked returned **metadata only, no imagery** (open question: where the imagery is held).

### 2026-09-10 · CSDA Planet download notebook (`946b7a7`); 2026-08-21 · CSDA download in `csdalib`
### 2026-03-24 · Earthdata S3 access notebook

---

## 4 · Sites and AOIs

### 2026-10-13 · Leetown Science Campus (USGS) added (`520e882`)
### 2026-09-22 to 2026-10-02 · Vendor request AOIs (uncommitted files in `sites/`)
- HydroSat (Kerry; per-site files for Algodones Dunes, Gobabeb TIR, Lake Tahoe, Oklahoma Ag Station, Salton Sea),
  HydroSat OR2, OroraTech OR2, Vantor Legion, Airbus (23 Sep), ESA misc (24, 28 Sep). Gobabeb TIR size edited (30 Sep).
### 2026-09-25 · HLS golden tiles GeoJSON (`abf2131`)
### 2026-09-24 · Two ESA sites (Leo) added to AOI maps; footprints map
### 2026-09-16 · GeoJSON for the Hydrosat request (`16a332b`)
### 2026-04 to 2026-07 · Site lists and request subsets
- Satellogic v2 request sites (Jul), onramp2 subset (Jun), notebook to prepare a GeoJSON subset for any vendor request,
  CR site-name fixes, interactive maps of CSDA and evaluation AOIs (May), SLI and CSDA evaluation sites (Apr).

---

## 5 · Footprints and acquisition summaries

### 2026-10-23 · Airbus / Satellogic satellite geometry for skyplots (`sensor_profiles.py`, `csdalib.py`)
- Bug: `airbus_dimap` mapped `INCIDENCE_ANGLE` and Satellogic `view:incidence_angle` to `satellite_elevation`.
  Incidence is a zenith angle, so near-nadir collects plotted near the horizon in `plot_skyplots_by_site_and_sensor`.
  Now stored as `incidence_angle`; `csdalib.derive_satellite_geometry` sets `satellite_elevation = 90 - incidence`.
- Pleiades 1A/1B DIMAP `AZIMUTH_ANGLE` is the along-track direction (~180 in 133 of 137 files), not the satellite
  azimuth. Satellite azimuth = AZIMUTH_ANGLE - atan2(tan(inc_across), tan(inc_along)). Checked against the bearing
  from scene center to strip `NADIR_LAT/LON` (LINEAGE/STRIP_*.XML), 134 MS files: median error 89° before, 0.1° after
  (max 2.6°). PNEO and SPOT `AZIMUTH_ANGLE` is already target -> satellite (tri-stereo order N -> overhead -> S on
  descending passes; SPOT median 1° from the nadir bearing); unchanged.
- Airbus angles now read from the `Center` Located_Geometric_Values block (was the first block: Top Center / TopLeft),
  as floats (the `'float'` cast is now implemented in `parse_metadata`).
- Existing footprint gpkg/csv still have the old values: rerun `footprint_CSDA_eval_all_data.ipynb`.
- Open: CSDA STAC `airbus-optical` carries the same PHR `view:azimuth` (= AZIMUTH_ANGLE) without the along/across
  incidence, so multistac skyplots of Pleiades 1A/1B azimuths from CSDA STAC are wrong and cannot be corrected from
  STAC fields. Satellogic `view:azimuth` direction not verified.
### 2026-10-23 · Duplicate deliveries and month heatmaps in `footprint_CSDA_eval_all_data.ipynb`
- New section after "Make Acqs (unique)": a duplicate is the same acquisition_id + image_type + product_level +
  radiometric_type + metadata file name at more than one path. The file name is needed because Pixxel (L1C/L2A) and
  Maxar Legion LV1B (M1BS/P1BS) leave those fields empty, which made 52 different products look like duplicates.
- On the 22 Oct outputs: 50 duplicated products (26 acquisitions), all Airbus plus 1 Satellogic `.ipynb_checkpoints`
  copy. Most are ad hoc top-level folders (`Airbus/7513399101`, `000410159_1_2_STD_A`, `PROD_SPOT6_001`, ...) repeated
  under `Airbus/Pleiades`, `PleiadesNeo` or `SPOT`.
- `Airbus/augmentation`: 83 acquisitions / 174 products; 81 acquisitions new; SPOT6 2025-08-30 (Gobabeb) and
  2025-10-23 (Railroad Valley), P + MS, already in `Airbus/SPOT`.
- Heatmaps: `multistac.month_table` + `multistac_plots.plot_month_heatmap` on the local footprints (unique
  acquisitions by affiliation/constellation/sensor; duplicate copies by delivery folder).
- Open: the scene search does not skip `.ipynb_checkpoints`; sensor profiles leave Pixxel product_level and Legion
  LV1B image_type empty.
### 2026-08-25 · SPOT6 duplicate acquisition ID fix
- Two SPOT6 acquisitions were linked to both Albuquerque and Shadnagar: acquisition ID too coarse in the Airbus DIMAP
  profile, per-file footprints sharing one ID, and site links aggregated by acquisition ID after `dissolve()`.
  Write-ups: `SPOT6_DUPLICATE_ACQUISITION_ID_FIX.md`, `SPOT6_DUPLICATE_ACQUISITION_ID_POSTDISSOLVE_FIX.md`.
### 2026-08-27 · Sensor profiles added (`f0fd64c`); 2026-08-25 · multi-site footprint bug fix
### 2026-07-01 · `csdalib` refactored for footprinting; HTML map of footprints
### 2026-02 to 2026-03 · First footprint and summary notebooks; R library for VHR metadata analysis

---

## 6 · Evaluation results, RadCalNet and spectral response

### 2026-11-02 · Timeline: Evaluation Results dB and comparison sheet (joint events)
- *CSDA Evaluation Results dB*: bar from **1 Jul 2026** (started July; exact day not recorded) to the joint
  ESA-USGS-NASA summary (1 Apr 2027), marked ongoing. One database on ADAPT with all CSDA SME evaluation results,
  for comparing results across vendors; a key feature of the joint activities.
- *Share joint evaluation comparison sheet with ESA & USGS (planned)*: not shared yet; started on ADAPT. **30 Nov 2026
  is a placeholder**; set the real date when shared.
- Both link to the slides: https://docs.google.com/presentation/d/1uKUrkPxlBLGDI_Hmr-jPj6sKqPC6RyhELhNlih5wFXU/edit?usp=sharing

### 2026-11-02 · Timeline: OroraTech, Orbital Sidekick, ImageSat and Satlantis TEMs
- `evaluations_list` now has **OroraTech**, **Orbital Sidekick**, **ImageSat** and **Satlantis** (8 panels). First
  entries: their technical exchange meetings with CSDA (Tue 25 Aug, Fri 16 Oct, Thu 22 Oct, Mon 2 Nov 2026); the
  timeline now starts in August. Joint events (VH-RODA, AGU, ESA
  template, ESA site list) show in their panels too.
- Airbus: the 24 Sep 2026 TEM (already on the timeline as " CSDA on-ramp 2 Space Reference Points (SRPs)") relabeled
  *Airbus Tech. Exchange Mtg. (TEM)* like the others; the SRP title moved into its note.

### 2026-11-02 · Timeline: Satellogic v2 plan
- Three Satellogic tasks (type Data Acq./Analysis, work weeks Mon-Fri): *Confirm STAC API search type with vendor* and
  *Build list of geometric/radiometric sites for v2* (2-6 Nov 2026); *Request v2 data from archive at sites*
  (9-20 Nov 2026).
- *Initial STAC analysis of v2 data* milestone on 27 Oct 2026: `multistac_site_analysis_satellogic.ipynb` built (date =
  the notebook's last save and checkpoint; not in git, creation date unknown).

### 2026-11-01 · Timeline: ESA reference site list (joint event)
- New joint event "ESA site list confirmed" on **24 Sep 2026** (date from the tab name), shown in every evaluation
  panel and linked to the `ESA_misc_20260924` tab (gid 564318517) of the site request sheet. 14 sites ESA wants for
  any vendor: Baotou, Gobabeb, Etang de Berre, La Crau TIR, Old Bahia Bridge, PICS Algeria-3, PICS Libya-1,
  PICS Libya-4, Piedmont, Salon-de-Provence, Shadnagar, San Mateo Bridge, Ankara, Grosseto (optical and thermal IR).
  This is the reference site list going forward.

### 2026-11-01 · Timeline: Vantor-Legion status (`notebooks/timeline.ipynb`, `html/timeline.html`)
- Notes for "Supplemental tasking windows" and "Receive additional data (radiometric)" rewritten so readers outside
  the project can follow them, with the 1 Nov results from `vantor_legion_supp_tracking.ipynb` (area 3). Replaces
  the 30 Oct "nothing delivered" note. Revised the same day to lead with Vantor's archive vs CSDA since the request
  (55 collected, 19 in CSDA); the notes are now generated by the tracking notebook's last cell.

### 2026-10-30 · Timeline updates (`notebooks/timeline.ipynb`, `html/timeline.html`; `201646f` to `352f08b`)
- **Satellogic** added to `evaluations_list` (own panel): "v2 evaluation" bar from **6 Oct 2026**, when the v2
  evaluation started with API access to the Satellogic STAC (Aleph v2 archive). The date is inferred from the first
  Satellogic API client code (`lib/satellogic_stac.py`, 6 Oct; `satellogic_auth.py`, 7 Oct); confirm. End date unknown:
  flagged `pending` (hatched, "Date TBD") with a 31 Dec placeholder.
- **HydroSat**: evaluation added with the 9 Oct TEM, and a "STAC API access" milestone on **15 Oct 2026** (client
  credentials received; enabled in multistac, see area 1).
- Airbus: schedule update applied (receive data by 1 Dec, brief HQ 15 Jan, brief Airbus 22 Jan, QA report 15 Feb,
  joint ESA-USGS-NASA summary 1 Apr 2027); data status from `airbus_order_tracking.ipynb` (29 Oct: 99 acquisitions,
  all on ADAPT; 22 of 93 new-tasking slots filled); ESA EDAP Pleiades / Pleiades Neo technical notes (19 Oct).
- Vantor-Legion: vendor briefed 19 Oct; supplemental tasking windows at WLEF and Valencia (17 Sep to 1 Nov), **nothing
  delivered as of 30 Oct** with 14 of 15 windows closed per site.
- Joint event: ESA Data Quality Statement template (29 Oct). The header links to `footprints_csda_map.html`, which had
  been empty since 24 Sep (sites with no geometry broke `m.save`) and was rebuilt from the 29 Oct footprints.
- Interactive timeline: `lib/timeline_template.html` + notebook export cell write `html/timeline.html`, served at
  https://pahbs.github.io/csda_summaries/html/timeline.html.
- Open: the saved plotly figure in the notebook still shows 3 panels (the HTML was rebuilt without plotly); re-run in
  the ILAB DEV kernel. Repo remote switched to SSH (`git@github.com:pahbs/csda_summaries.git`).

### 2026-09-24 · Timeline notebook (`ed05d58`)
### 2026-09-15 · `evallib.r` and evaluation results notebooks; 2026-09-10 · results database build notebooks
### 2026-09-14 · AERONET-OC search notebook; two evaluation sites added to the database
### 2026-07-09 · RadCalNet API access, download and plotting (`radcalnetlib.py`); Legion preliminary results

---

## 7 · Repository and docs

### 2026-10-15 · Uncommitted state
- Modified: multistac libs, `stac_auth.py`, `stac_providers.yaml`, `staclib.py`, many notebooks; deleted:
  `results_legion_*.ipynb`, `csdalib_refactored.py`, `stac_collections.md`; untracked: new libs (`csdalib_v2.py`,
  `satellogic_*.py`, `searchlib.py`), notebooks, site files, `.readthedocs.yaml`.
- **Do not commit** `notebooks/s3_tmp_credentials.json`; consider ignoring `notebooks/__pycache__/` and data outputs
  (`*.gpkg`, `*.xlsx`, `stac_items_*.json`).
### 2026-02-25 · Repository created; README; Sphinx docs (`docs/`)

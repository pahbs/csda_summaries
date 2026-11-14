# csda_summaries: activity log

What was done, decided or found in this repo, grouped by area. **Newest entries at the top**, both in "Recent activity"
and within each area. Add new work as a one-line item in Recent activity and as a dated entry in its area (top of the
area). Committed work: see `git log`; this log also covers uncommitted work, decisions and open issues.

**Areas**
1. [Multistac: unified search library](#1--multistac-unified-search-library): `lib/multistac*.py`, `lib/stac_providers.yaml`,
   `lib/stac_auth.py`, `lib/sensor_catalog.yaml`, `tests/smoke_multistac.py`
2. [Archive analyses: site and global](#2--archive-analyses-site-and-global): `notebooks/multistac_site_analysis_*.ipynb`,
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

- 2026-11-14 · [2] Density page: "Interactive globe" option (MapLibre GL, loaded on first use): the same cells, colors, legend and controls on a zoomable 3D globe (or flat map), gray land by default or Esri imagery, hover tooltips; zoom capped at regional scale.
- 2026-11-13 · [2] Density page: legend moved to the top right of the map card, opposite the heading. Commercial switch: `python lib/archive_density.py commercial hide|show [--push]` greys out the commercial tabs (Landsat and Sentinel-2 stay), takes their counts out of the page and moves their data files from the data repo to monthly_fp/withheld/ (full page kept there); show restores both. A rebuild while hidden stays hidden.
- 2026-11-13 · [1] First look at 120 sites: the 78 CSDA optical/thermal sites plus 42 Misc sites (FireSense and SLI-FUSION fire perimeters, surface water, bathymetry; not the USGS ARD tiles), from sites/eval_sites_aoi.geojson. Daily job reworked: vendors side by side (own logs), 4 h limit each, new sites in batches of 6 saved as they go, failing sites retried next day instead of discarding the vendor's run, publishing driven by what was last published. multistac sends outlines over 500 vertices as their convex hull (Kuva answered HTTP 413 to fire perimeters). Restored archive_dashboard.VENDORS (deleted by the Misc-site edit, which broke publishing on 12 Nov). Candidate acquisitions folder on ADAPT: lib/candidate_watch.sh (cron, every 10 min) builds a thumbnail page next to each selection zip dropped in (at most 600 acquisitions), with a status file. jupyter_page: both spellings of the home folder.
- 2026-11-13 · [1][2] Archive pages: compact summary tiles (label beside the number); "Last updated" as an ink pill with its age (flagged past a week), and on the first look "refreshed daily, starting 3 am ET"; first-look filters in a fixed two-row layout for every vendor (controls that do not apply stay in place, greyed); "Sorted by Candidate Acquisitions" removed; EarthDaily's constellation is EDC.
- 2026-11-13 · [2] Density: Airbus from its own catalog (OneAtlas STAC), Jan 2020 – Nov 2026: Pleiades 2.0M, Pleiades Neo 1.6M, SPOT 6/7 1.3M acquisitions (an Airbus catalog item is about one acquisition). Sentinel-2 complete (83 months; 2020-21 no longer double counted). multistac read sensor_catalog.yaml once per item for the orbit altitude (Airbus: elevation from incidence angle): now read once, a month of Airbus 4.5 min instead of 15+. Data file names from letters and digits only (SPOT 6/7 -> airbus-spot-6-7).
- 2026-11-12 · [1] Thumbnail reviews saved next to the selection: the viewer page is written beside the selection .zip and shown in the notebook output (`lib/jupyter_page.py`), where it runs in JupyterLab's own origin and writes `<selection>_review_<date>_<id>_kept.csv` and `.json` through Jupyter's contents API; on open it restores the latest saved review. Pages opened from the file browser are sandboxed by Jupyter (`/files/` carries `sandbox allow-scripts`) and fall back to a .zip download.
- 2026-11-12 · [1] Thumbnail viewer takes the first-look selection .zip (exact tab, the first look's own site set including Misc sites, selection ID / note / limits shown). Drop reasons (1–6 keys), kept vs each site's minimum, unique count. "Save review" .zip: kept CSV (selection_id, review_id) + JSON with every decision, counts and the whole selection; "Load review" restores decisions. The first look also loads a review .zip (restores its selection).
- 2026-11-12 · [1] Archive First Look: saved selections. "Save selection" downloads a .zip with the CSV and a JSON record (note, limits, per-site limits applied, sites, months, catalog search date, rule `candidate-v1`, counts by site and month, the acquisition IDs); the filename carries the main dials and a selection ID. "Load a saved selection" restores it and compares with today's list. Both archive pages: "vendor" removed from titles and text; "How to read" headings name the affiliation (colored dot, bold) and constellation.
- 2026-11-12 · [7] Top-level clean-up: this log moved to `docs/LOG.md`; `MULTI_STAC_SEARCH_PLAN.md` and the two SPOT6 write-ups to `docs/notes/`; `run_distributed_global_search.sh` to `lib/` (it finds the repo one level up).
- 2026-11-12 · [1][2] Airbus catalog access works: OneAtlas STAC at search.foundation.api.oneatlas.airbus.com/api/v1/stac (collections PLEIADES, PLEIADES-NEO, SPOT; ~65,000 items a month), API key in [Airbus_STAC_API]. Profile enabled; first look searching its history at the 78 sites (Airbus's own catalog only: CSDA's airbus-optical IDs do not match its acquisition IDs). Density: Landsat 8/9 complete; Sentinel-2 2020-21 refetched after finding every tile there twice (original and reprocessed baseline), datatake ID now without the baseline; SuperDove days complete.
- 2026-11-11 · [2] Density dashboard: Count selector (Acquisitions, or Days with an acquisition: days in the month with at least one acquisition in the cell, 0-31, comparable across vendors whatever their unit) and Scale selector (this constellation, or one shared log scale for all). Days from stored dates for footprint vendors; Landsat and Sentinel-2 count them while fetching (backfills restarted to include them); SuperDove from Planet's stats by day (`archive_density.py days superdove`, shown once complete). Combined views stay on acquisitions.
- 2026-11-11 · [2] Density dashboard: Landsat 8 and 9 (USGS / NASA) and Sentinel-2 (ESA) tabs from Earth Search (Element84, no login; new `earth-search` profile, page size 200). Too large to keep item by item, so `fetch_counted` counts each month per 0.5° cell as it is fetched (a pass once per cell: Sentinel-2 datatakes, Landsat scenes < 2 min apart) and keeps only the counts. Backfill running, one process per year on forest201/202/203 (`monthly_fp/{sentinel2,landsat}_*_run.log`); uncounted months show as not fetched yet. Footprint counting now works per item, deduplicated per acquisition and cell (same results, faster).
- 2026-11-11 · [2] First look grouped by vendor like the density page (one tab per vendor, a Constellation picker for Planet and Vantor). Both pages have Airbus (Pléiades, Pléiades Neo, SPOT 6/7) and EarthDaily (EarthDaily Constellation) tabs marked "Available pending API access" (`archive_dashboard.PENDING_VENDORS`); a vendor's placeholder goes away once its data arrive.
- 2026-11-11 · [2][7] First look renamed *Vendor Archive First Look: identify Candidate Acquisitions for CSDA evaluation*; "Good Quality" is now "Candidate Acquisition" everywhere on the page, as a tag in the vendor's color. New affiliation colors (`vendor_specs.AFFILIATION_COLORS`): the seven vendors on the archive pages pass the dataviz checks as a set (all pairs, light and dark: OKLab ΔE ≥ 15.6 normal vision, ≥ 8.0 protan/deutan, contrast ≥ 3:1); every pair of the 20 affiliations is ≥ 15 apart. Hydrosat green, Kuva violet, Satellogic teal, Vantor blue; Airbus, EarthDaily, Planet keep their hues. Applied to the first look, density, vendor specs and thumbnail pages.
- 2026-11-11 · [2] Archive first look refreshed daily (cron, `lib/first_look_daily.sh` -> `lib/first_look_daily.py`): per-vendor caches in `multistac/first_look_cache/`; each day the last 90 days are searched again at every site, and a site new to the sites file (or with a changed outline) is searched over the vendor's whole history. Tab summaries now live in the data repo (`archive_first_look/index.json`), so the page in this repo no longer changes on a refresh.
- 2026-11-11 · [1][2] Thumbnail page renamed *Acquisition Request Check* (vendor tag in its affiliation color, less text). Airbus (OneAtlas) and EarthDaily (EarthPlatform STAC) prepared, off until access: profiles in `stac_providers.yaml` (`enabled: false`), new login type `oauth2_api_key` (Airbus) and `client_auth: basic`, first-look tabs, thumbnail sources, daily-job entries; `tests/smoke_provider.py <name>` checks a new provider. Timeline: Joint Activities entry for the daily search of all sites.
- 2026-11-11 · [3] Tracking run (Airbus, Vantor Legion): nothing new in CSDA STAC since 10 Nov; everything in CSDA at the tracked sites is on ADAPT (Airbus 197 acquisitions, Legion 68). Vantor has collected 44 Legion images since 1 Sep not yet in CSDA (15 meet the site requirements).
- 2026-11-10 · [2] Density dashboard at 0.5° (was 1.5°), each acquisition counted in every cell its outline touches (was: its center only). Outlines re-fetched for all catalogs since 2020 into `global_analysis/monthly_fp/` (now the default store); SuperDove recounted from Planet's statistics at 0.5°. Every constellation loads on demand from the data repo (~15 MB compressed in all).
- 2026-11-10 · [2] Archive first look: every tab now covers the same 78 sites, the CSDA sites for optical or thermal validation (`csda_sites_aoi.geojson`, domain contains Optical or Thermal, whole sites only), defined once in `archive_dashboard.load_sites()`. Before: 58 optical sites (Hydrosat: its 29 request sites). All tabs re-searched; Satellogic's busy months retried in halves.
- 2026-11-10 · [3] Hydrosat order 9265 (417 presigned links, L1b and L2 from VZ01 and VZ02) downloaded with the vendor's `download_presigned.sh` into `/explore/nobackup/projects/CSDA_eval/Data/Hydrosat/cac/` (named `cac` so it is clearly not from the CSDA STAC); links expire 13 Nov.
- 2026-11-10 · [7] Large page data moved to its own repository, `pahbs/csda_summaries_data` (GitHub Pages at pahbs.github.io/csda_summaries_data/, one commit replaced on each push, via `lib/data_repo.py`). The first-look and density pages read their data from there; `html/archive_first_look_data/` and `html/archive_density_data/` are no longer in this repo.
- 2026-11-09 · [2] Planet on the first-look page: SuperDove (129k strip-site acquisitions since 2020, loaded on demand, one sensor column) and Tanager tabs, from `notebooks/multistac_site_analysis_planet.ipynb`. Tanager density complete (68k strips; counted as strips). Density timeline: *This month* now highlights only the month on the map. Busy footprint maps draw the newest 300.
- 2026-11-09 · [2] Thumbnail viewer (`lib/thumbnail_viewer.py`, `notebooks/thumbnail_viewer.ipynb`): a first-look CSV becomes a private page on ADAPT of vendor previews (Vantor browse GeoTIFF exact; Planet, Satellogic, Hydrosat placed on bounding boxes; Kuva has none) with keep/drop and a CSV of kept. Output in `/explore/nobackup/people/pmontesa/multistac/thumbnails/`.
- 2026-11-09 · [2] Archive first look: the map card is now *Acquisition Locations*; selecting a site shows the footprints of its good and Check AOI acquisitions over imagery (Leaflet), loaded per site from `html/archive_first_look_data/fp/`.
- 2026-11-09 · [1][2] Planet added as a provider (`planet`, STAC API at api.planet.com/x/data; key from `[Planet_STAC_DATA_API]` as Basic auth username, new `api_key_basic` in `stac_auth.py`; one acquisition = one strip). Density page: Planet tab with SuperDove (592 M scenes since 3/20, counted per 1.5° land cell with Planet's stats endpoint, loaded on demand) and Tanager (backfill running). First-look Planet tabs to follow.
- 2026-11-08 · [2] `archive_density.html`: Vantor tab now holds Legion, WorldView-2 and WorldView-3 (Vantor catalog `wv02`, `wv03-vnir`, since 2020), shown separately or combined. WorldView backfill runs newest first with a commit and push after each year.
- 2026-11-07 · [2] New `html/archive_density.html` (`lib/archive_density.py`): monthly global acquisition density since 2024 for Vantor Legion (1.0 M strips), Hydrosat VanZyl (161 k scenes), Kuva Hyperfield (2.2 k captures) and Satellogic Aleph-1 (thumbnail captures, version ≥ 1), animated with a slider. Months stored in `multistac/global_analysis/monthly/`; monthly update = `fetch <vendor>` then `build` (re-fetches the last 3 months). Satellogic global search needs ~3-day windows (HTTP 502 beyond).
- 2026-11-07 · [2] New `html/archive_first_look.html` (`lib/archive_dashboard.py`): one tab per vendor constellation (Hydrosat VanZyl, Kuva Hyperfield, Vantor Legion, Satellogic Aleph-1) with the same layout: good acquisitions by site and sensor, with limits set on the page. The site notebooks publish to it; new `multistac_site_analysis_legion.ipynb`. *Check AOI* marks whole-scene values above a site's cloud limit but within the scene limit, as in the Legion tracking.
- 2026-11-07 · [3] Airbus and Legion tracking notebooks rebuilt on one layout and a shared `lib/tracking_report.py`: each ends with what is new since the last run, the HTML summary (now written by the notebook, with products and processing levels in plain terms) and the download of anything not on ADAPT. Run 7 Nov: 46 products (84 GB) downloaded, footprints rerun, timeline updated.
- 2026-11-07 · [2] `multistac_site_analysis_hydrosat.ipynb` runs: reads the local workbook (`API search` tab; 29 sites, 2 mapped by coordinates, non-breaking space fixed in `lib/site_request.py`). 93 acquisitions at 24 sites at the Hydrosat API, none at CSDA, with `CLOUD_COVER_MAX = 0`. Searches L1B and L2 only: L1A and nighttime items have no cloud cover, and a scene's L1A shares its `hydrosat:scene_id`, so L1B results carry over if L1A is ever ordered.
- 2026-11-06 · Hydrosat site search reads its sites from the requests workbook (`lib/site_request.py`): SharePoint through Microsoft Graph sign-in, or a local copy. The live sign-in is untested and needs a registered app ID.
- 2026-11-06 · Hydrosat site search: `multistac_site_analysis_hydrosat.ipynb` rewritten for all Optical and Thermal sites at CSDA STAC and the Hydrosat API, with a download set up but not run. CSDA holds 4 Hydrosat products, none at these sites.
- 2026-11-06 · [6] RSR database: curves added for MODIS, VIIRS, Sentinel-3, Landsat 5 and 7 (measured) and Tanager and Pixxel Firefly (modeled); dashboard updated. 29 constellations still have none.
- 2026-11-06 · [6] Vendor Specs dashboard: one set of filters pinned above the tabs, driving every tab.
- 2026-11-06 · [6] Vendor Specs dashboard: new *Spectral Response* tab (interactive RSR curves in the style of `build_rsr_db.ipynb`).
- 2026-11-06 · [6] Timeline: Vendor Specs dashboard linked in the page links beside the footprints map.
- 2026-11-06 · [6] Vendor Specs dashboard: *Cross-track swath width* gets a Map view (swath squares at true scale around a chosen evaluation site; Esri imagery or terrain layers); the panels stay as a second tab. EnMAP added, systematic imagers' revisit corrected, Vantor recolored.
- 2026-11-06 · [4] Evaluation Sites: 41 SLI-FUSION AOIs in the sheet (rows 623-663, 8 new columns, `site_id` repaired), sites file and evaluation map rebuilt (662 sites); map header shows a Work in progress badge and Last update date.
- 2026-11-04 · [6] Draft *Suggested Best Practices for Compiling Joint Evaluation Results* and data frame templates, for the 4 SME groups, USGS and ESA (`eval_results_exchange/`); `evallib.r` now standardizes site names from the sites database.
- 2026-11-04 · [7] Published maps moved from `notebooks/` to `html/` (`footprints_csda_map.html`, `aoi_csda_sites_map.html`, `aoi_eval_sites_map.html`); notebooks and links updated.
- 2026-11-04 · [7] Repository cleanup: working code, site AOIs and notebooks committed; checkpoints untracked; local `.gitignore` extended (secrets, generated files, vendor order tracking, draft evaluation results).
- 2026-11-04 · [6] Timeline: Highlight and Find controls as on the Vendor Specs page; Joint Activities is now a lane like each evaluation (chip, card, rows).
- 2026-11-04 · [6] Timeline: *Augmentation data on ADAPT* entries (4 Nov) for Airbus and Vantor-Legion, each linking a per-site summary table in `html/augmentation/`.
- 2026-11-04 · [3] Vantor Legion: 48 CSDA acquisitions at the request sites not on ADAPT downloaded (134 products, 225 GB) to `Data/Maxar/Legion/augmentation` (`vantor_legion_supp_tracking.ipynb` §10); 19 passes delivered twice (radiometric enhancement off + ACOMP).
- 2026-11-04 · [2] `multistac_site_analysis_kuva.ipynb`: Kuva Sense acquisitions at the CSDA sites (618 acquisitions, 1,804 products, 22 sites, cloud ≤ 20%).
- 2026-11-03 · [1] Multistac: Kuva Space enabled (`kuva` provider): Kuva Sense Products search as STAC-like items, password-grant tokens (8 h, renewed automatically).
- 2026-11-03 · [6] Vendor Specs: Pixxel Firefly added as 6 new rows (86–91, 162 cells) from public sources, through the edit record (`specs/public_check_2026-11-03_pixxel.csv`); not yet in the Google Sheet.
- 2026-11-03 · [6] Vendor Specs: revisit estimates for the Google Sheet (6 columns + notes, `specs/revisit_estimates.csv`, Apps Script `specs/write_revisit.gs`); Revisit tab grouped by sector / data owner and colored by *Color by*; byline on the dashboard.
- 2026-11-03 · [6] Vendor Specs: *Revisit* tab: mean revisit at 0°, 40°N and 60°N simulated from each orbit (≤ 20° view angle or full agility; whole year or June–August), replacing the sheet's mixed-definition *Revisit Time* in the comparison.
- 2026-11-03 · [3] Vantor and Airbus: simple "since September" summaries (new in CSDA STAC since 9/1; for Vantor also collected but not yet in CSDA) in `vantor_legion_supp_tracking.ipynb` §9 and `airbus_order_tracking.ipynb` §4b; timeline notes updated from them.
- 2026-11-02 · [6] Timeline: Joint Activities entry *NASA-USGS Airbus Optical Evaluation Methods and Results mtg.* (2 Nov 2026).
- 2026-11-03 · [6] Vendor Specs: all 138 recorded edits now in the Google Sheet (Apps Script `specs/apply_edits.gs`, sheet tab *Edit log*); the M77/M78 Orbit Type case change was withdrawn (rejected by the sheet's dropdown).
- 2026-11-02 · [6] Vendor Specs: the 86 proposed edits are applied (140 cells) and recorded per cell in `specs/edits_log.csv`; checks fall from 75 to 45 flagged cells. Dashboard: *Cross-track swath width* section, *Database Quality* tab with the edit record.
- 2026-11-02 · [6] Vendor Specs: rule *Total Bands (MS)* counts pan; public-source check (87 proposed edits, 71 from CSDA vendor pages, `specs/public_check_2026-11-02.csv`); interactive dashboard `html/vendor_specs.html` (hover details, sector / status filters, light / dark).
- 2026-11-02 · [6] Vendor Specs DB: `lib/vendor_specs.py` + `csda_specs_compare.ipynb`: live load, QA checks on columns A–AS (76 suspect cells in 50 of 84 rows), completeness grid (A–AS 56% filled), NASA Chat extraction prompt + diff, and footprint / GSD / band-count comparison figures.
- 2026-11-02 · [6] Timeline: joint evaluation comparison sheet shared with ESA & USGS on 29 Oct 2026 (was planned, placeholder 30 Nov).
- 2026-11-02 · [6] Timeline: Planet-Tanager added as an evaluation (own panel) with the Planet Tanager TEM (28 Aug 2026).
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
- 2026-10-11 · [1] Multistac plan and phases 1–4 (`docs/notes/MULTI_STAC_SEARCH_PLAN.md`).
- 2026-10-02 · [2] CSDA STAC search tutorial notebook.
- 2026-09-30 · [4] Gobabeb TIR site size edited; HydroSat request AOIs (Kerry) through 2 Oct.
- 2026-09-30 · [2] Distributed global CSDA search script (`lib/run_distributed_global_search.sh`).
- 2026-09-25 · [4] HLS golden tiles GeoJSON.
- 2026-09-24 · [6] Timeline notebook; [4] two ESA sites (Leo) added to AOI maps.
- 2026-09-22 · [4] Request AOIs: Airbus, OroraTech, Vantor Legion, HydroSat OR2.

---

## 1 · Multistac: unified search library

### 2026-11-03 · Kuva Space enabled (`kuva`)
- Access: Kuva Sense account, Products endpoints only (no downloads). Login = OAuth2 password grant at
  `/api/login/token` (form: username, password); tokens last 8 h, no long-lived keys. New auth type
  `oauth2_password` (`stac_auth.OAuth2Password`): INI section `[Kuva_STAC_API]` with `username` and `password`; token
  requested again before 8 h (`token_lifetime_s: 28800`) or after a 401; only the HTTP status is reported on failure.
- The account's STAC API (`/api/stac`, collection `Hyperfield-1`) authenticates but returns no items, so a new backend
  `api: kuva_products` (`multistac.KuvaProductsProvider`) wraps `/api/products/search` (geometry, dates, cloud cover,
  processing level, page / page_size) and returns STAC-like items, as the CMR backend does. Collections = processing
  levels `L1B`, `L1C`, `L2A` (default all three). Each level of a capture is its own product id;
  `kuva:raw_product_landing_id` is shared by a capture's levels, so it is the `acquisition_id`. Cloud cover (percent)
  is sent with the request (`cloud_cover_percentage`, required) and re-applied locally. `overview()` gives first / last /
  total per level; monthly catalog counts work too.
- `sensor_catalog.yaml`: Hyperfield-1A / HF-1A -> Kuva Space, Hyperfield, HF-1A.
- Smoke test (2025-01-01 to 2026-12-31, cloud ≤ 20%): catalog L1B 2,181 / L1C 1,821 / L2A 1,815 products since
  2025-01-24; Gobabeb 121 and Railroad Valley 99 acquisitions (HF-1A and HF-1B), none at Valencia or WLEF; heatmap by
  site and sensor works.
- Use: `EXTRA_PROVIDERS = {'kuva': None}` (or `['L2A']`) in the site-analysis notebooks.

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
- `docs/notes/MULTI_STAC_SEARCH_PLAN.md`: phases 1–4 for CSDA and Satellogic (`stac_providers.yaml`, `stac_auth.py`,
  `multistac.py`, smoke tests, tutorial).

---

## 2 · Archive analyses: site and global

### 2026-11-11 · Daily first look, with new sites searched from the start
- Cron on forest202 at 3 am: `lib/first_look_daily.sh` (lock, log per day in `first_look_cache/logs/`, kept 60 days). Per vendor: compare `archive_dashboard.load_sites()` with `first_look_cache/<vendor>/sites.json` (name -> outline hash); new or changed sites searched from 2020, removed ones dropped; the last 90 days searched again everywhere and replaced; failed windows retried in halves; a vendor still failing keeps its cache and tab. Tabs republished only when their rows change; then `index.json` is rebuilt and the data repo pushed.
- First run 11 Nov: Kuva, Hydrosat, Legion, WorldView searched in full (minutes each); Satellogic and Planet seeded from the 10 Nov full searches. Planet's republish (SuperDove footprints) takes ~40 min, so a nightly run is ~50 min. Tested: a site removed from the Kuva cache was found and searched again, giving the same rows as the full cache.
- The notebooks' publish cells still work, but the daily job now keeps the page current; a notebook publish is replaced at the next change.

### 2026-11-10 · Density dashboard: 0.5° cells from footprints
- `archive_density.py` defaults: `STORE` = `global_analysis/monthly_fp/` (one simplified outline per item, WKB) and
  `CELL_DEG` = 0.5. The old point store `monthly/` is kept but no longer used. A cell's number is now how many
  acquisitions cover it, so long strips count along their whole length.
- Counting bug found in the first 0.5° build, fixed before publishing: rasterizing all outlines at once with
  `all_touched` and an adding merge counted edge cells several times per polygon (up to 15 for a long diagonal strip;
  Satellogic ~7× too high). `_footprint_counts` now tests each outline against the cells of its bounding box
  (vectorized shapely), checked against one-at-a-time rasterizing; ~50× faster, a full build takes ~4 min on a forest node.
- Satellogic's straight-edged blocks (Yukon, BC, Middle East, SE Australia) are real: long ~2° × 7.5° catalog strips
  imaged repeatedly in 2023–24 (checked cell counts against the footprints).
- Data per constellation in the data repo (`archive_density/<key>.json`): 60 MB, ~15 MB gzip; SuperDove 31 MB (8 MB).

### 2026-11-10 · First look on the optical and thermal validation sites
- One site set for every tab: `archive_dashboard.SITES` (`sites/csda_sites_aoi.geojson`) with `SITE_FILTERS` (Remote
  Sensing Domain contains Optical or Thermal; `feature_type` = site, so the FMI corner-reflector points are left out):
  78 sites, 54 optical (7 also thermal) and 24 thermal. The Kuva, Satellogic, Legion and Planet notebooks use the same
  filter; the Hydrosat notebook keeps its site request for its own analysis and publishes on `load_sites()`.
- Hydrosat's request site `CA_SanFrancisco_1_B23` (SLI, next to SF Bay Bridge) is not in the set.
- Re-searched 10 Nov on forest203 (`multistac/site_analysis/first_look_refresh/`): Hydrosat 829 acquisition-site rows,
  Kuva 1,407, Legion 6,115, WorldView 11,628, SuperDove 176,047, Tanager 1,367, Satellogic 21,862. Planet: only the
  new sites were searched and merged into `planet_sites/<year>.pkl` (backup of the optical-only files in
  `planet_sites/optical_sites_only_20261110/`). Satellogic: 9 month searches at Railroad Valley failed (HTTP 502) and
  were retried in halves; the notebook's publish cell has no such retry yet.

### 2026-11-04 · Kuva site analysis (`multistac_site_analysis_kuva.ipynb`)
- From the Satellogic notebook: `kuva` L1B / L1C / L2A + CSDA `kuvaspace` (no items found there), 2025-01-01 to
  2026-12-31, cloud ≤ 20%. Acquisition heatmaps by site and satellite (one acquisition = `raw_product_landing_id`, all
  levels), per-site tables, density map. No skyplot: Kuva products have no view or sun angles. Kernel: ILAB TensorFlow.
- Per-site counts use `res.gdf` (one row per site an item falls on): the de-duplicated `gdf` dropped captures that cover
  two nearby sites (La Crau / Salon-de-Provence, the FMI CR Array sub-sites), 18 instead of 22 sites.

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
- `lib/run_distributed_global_search.sh`: splits the world into longitude bands across nodes, `searchlib` logic per band.

### 2026-03 to 2026-07 · CSDA STAC searches (staclib)
- `staclib.py` searches, seasonal search by months (Jul), Legion example (Mar–Jun), multiple-collection examples.

---

## 3 · Data requests and downloads

### 2026-11-10 · Hydrosat order 9265 downloaded (vendor presigned links)
- `HydrosatRequest.zip` (README, `download_presigned.sh`/`.ps1`, `id_9265_all.txt` with 417 CloudFront presigned links
  under `csdap-nga-collections/Hydrosat/NonDomestic/`) unpacked to `Data/Hydrosat/HydrosatRequest/`.
- Downloaded into `Data/Hydrosat/cac/` (keeps the vendor's `Hydrosat/NonDomestic/<scene>/` layout); log
  `Data/Hydrosat/cac_download.log`. `cac` marks data delivered outside the CSDA STAC. Links expire 13 Nov 2026 12:08 EST.

### 2026-11-07 · Tracking notebooks made consistent (`lib/tracking_report.py`)
- `airbus_order_tracking.ipynb` and `vantor_legion_supp_tracking.ipynb` share sections 2, 3 and 5–8 and the parameter names; only
  1 (what was requested) and 4 (compare with the request) are vendor-specific. Section 8 prints the same three results.
- **New** = not in the last run's list (`OUT_DIR/runs/products_YYYYMMDD.csv`), since CSDA STAC has no date added. This finds late
  deliveries that an "acquired since" date misses. The last run is the latest before today, so same-day re-runs agree. The
  first lists were rebuilt from the 7 Nov search: Airbus 3 Nov (492 rows, as that run reported), Legion 4 Nov (189 rows).
- **On ADAPT** is per product in both (folder with all assets, or footprints). Legion was per pass, which hid 20 products of passes
  on ADAPT; item ids come from the footprint file names (`-M2AS-200014660685_01_P001` = `200014660685_01_P001_M2AS`).
- **Download** = every CSDA product at the sites not on ADAPT, in both. Airbus followed the sheet only, so `PNEO3_202610260345575`
  (no free slot) was never fetched. Airbus now searches without the cache, which replaces its two extra searches.
- **HTML pages** were made by hand; the notebooks now write them at the same addresses. They reproduce the old totals (Legion 48
  acquisitions, 134 products, 19 / 10 / 19; Airbus 101, 222, 91 TOA only, 10 both), and now cover all that is available.
- Run on 7 Nov: Airbus 198 acquisitions, 4 new, 18 products (8 acquisitions, 40.7 GB) downloaded, including 3 archive acquisitions
  outside the sheet; Legion 68 acquisitions, 3 new, 28 products (16 acquisitions, 43.2 GB) downloaded. All complete: 502 of 502 and
  201 of 201 products on ADAPT. Footprints rerun: `Airbus/augmentation` 109 acquisitions, 240 products; all 201 Legion products found.
- The footprint run's site coverage maps (cell 43) timed out on a network connection, and
  `Airbus/HD15/000501695_1_1_HD_A/.../IMG_PNEO4_HD_202510051040574_PMS_...R1C1.TIF` could not be read (bad TIFF directory).
- SME pages: "TOA" differs by vendor: Airbus `RFL` pixels are reflectance, Vantor enhancement `Off` pixels are calibrated DN needing
  `absCalFactor`. Terms confirmed from delivered `DIM_*.XML` and `.IMD` files (`LV2A` = coarse DEM, `LV3D` = fine DEM, `SEN` = sensor).

### 2026-11-04 · Legion download to `Data/Maxar/Legion/augmentation` (`vantor_legion_supp_tracking.ipynb` §10)
- Same method as the Airbus download (`CsdaClient` + `csdalib_download.download_all_assets`): CSDA Legion acquisitions at the
  request sites that section 5 does not find on ADAPT. `MEETS_ONLY = False` (all of them; `True` = meeting the requirements).
  `legion_request_products.csv` in the folder gives site and acquisition per product.
- 4 Nov: 48 of 65 acquisitions (Libya-4 10, Valencia 9, WLEF 9, Gobabeb 8, Golmud 7, Railroad Valley 4, Baotou 1),
  134 LV2A products (`M2AS` / `P2AS`), 225 GB, all complete.
- Footprints rerun after the download (`footprint_CSDA_eval_all_data.ipynb`, 4 Nov): all 48 found, so all 65 CSDA Legion
  acquisitions at the request sites are now on ADAPT (598 unique local acquisitions, 120 Legion).
- **19 passes come under two order IDs**, same scenes and tiling, different radiometry (`.IMD` `radiometricEnhancement`):
  `Off` (with `absCalFactor`) and `ACOMP` (atmospheric compensation, `absCalFactor = -999`, no standard TOA conversion).
  10 more passes exist only as ACOMP. CSDA STAC shows both as LV2A, so only the IMD tells them apart.
- Resume fix (here and in `airbus_order_tracking.ipynb` §6): a product counts as downloaded only when its folder holds all
  of the item's assets. The old check (any file in the folder) would never refetch a tile missing after an interrupted
  download (2 Legion pan products were one tile short; refetched).
- `Data/Airbus/augmentation` was owner-only (`drwx------`, likely the JupyterLab umask); `chmod -R go+rX` on 4 Nov. Check
  permissions after future downloads from JupyterLab.

### 2026-11-03 · Since-September summaries for Vantor and Airbus (timeline notes)
- Both notebooks end their analysis with a short section: a per-site table, plain-language conclusions and the timeline
  note. "New" = **acquired** on or after `SINCE` (2026-09-01): CSDA STAC items carry no added / updated date, so delivery
  dates cannot be counted.
- **Vantor** (`vantor_legion_supp_tracking.ipynb` §9; replaces the old notes cell): fresh Vantor Discovery search since
  `SINCE`, matched to CSDA by site, sensor and time (`MATCH_SECONDS`). As of 11/3/26: 19 Legion images new in CSDA at 3 of
  9 sites (Valencia 9, WLEF 9, Golmud 1), 4 meet the site requirements; Vantor collected 57, so 38 (67%) are not in CSDA
  yet (WLEF 14, Valencia 14, PICS Libya-4 5, La Crau 2, Railroad Valley 2, Golmud 1), 9 of them meet the requirements.
  Nothing new at Baotou, Gobabeb, Sioux Falls. Check: every CSDA image since 9/1 is in Vantor's catalog.
- **Airbus** (`airbus_order_tracking.ipynb` §4b, before the Excel copy): fresh CSDA search since `SINCE` at all 8 tracked
  sites (the §2 search is cached). As of 11/3/26: 23 images new in CSDA at 6 of 8 sites (Baotou 9, WLEF 7, Golmud 2, PICS
  Libya-4 2, Railroad Valley 2, Valencia 1), 6 with SR, 18 fill tasking requests; tasking requests (TOA and SR cells)
  24 of 93 filled, 69 waiting (WLEF 29, Valencia 22, Golmud 15, Baotou 3). Collected but not delivered: unknown (no
  Airbus catalog access). Run through §4b only (in a copy, outputs copied back): §5 writes the Excel copy and §6 downloads.
- Timeline: notes of Vantor-Legion *Receive additional data* and *Supplemental tasking windows*, and Airbus *Receive
  additional data*, replaced with these.

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

### 2026-11-05 · SLI-FUSION AOIs in the Evaluation Sites database (`sites/sli_fusion_aois/`)
- Package built with NASA Chat from the SLI FUSION SharePoint material: 41 AOIs (12 wildfire, 9 FireSense-campaign fires, 11 USGS ARD
  tiles, 4 bathymetry, 5 surface water). Sheet tab `Evaluation Sites`: rows 623-663, new columns Z:AG (`aoi_id` to `geometry_version`).
  Read back through `read_from_sheet`: 662 sites, 165 CSDA unchanged, 0 cells changed in the 621 existing rows, 0 mismatches.
- `new_eval_sites_rows_checked.csv` is what was written. Changes from NASA Chat's file: `parent_aoi` for both Little Giant rows (spatial
  join gives 3 links, file had 1), ISO dates, and per Paul: `Evaluation Category = All`, `Remote Sensing Domain = Misc`,
  `Program Use = SLI-FUSION` for all. `Assessment type(s)` left as `Radiometric & Geometric`.
- `csda_eval_sites_process.ipynb`: 5 GeoJSONs added to `multi_site_geojson_dict`; SLI-FUSION geometry simplified (0.0003 deg, ~30 m, then
  `buffer(0)`, because simplifying left 3 invalid) for `eval_sites_aoi.geojson` only: 4.4 MB instead of 25.5 MB, max boundary shift 30 m.
- The package expected 663 sites; 662 is right: the old file had Fort Huachuca twice.
- Column A (`site_id`) was `#REF!` on every row; formula restored (`=IF(C2<>"",MAX($A$1:A1)+1,"")`), so it numbers rows in sheet order, 1-662. Not
  a stable ID: sorting or inserting rows renumbers sites; use `Site Name`. Nothing in the code reads it.
- Rebuilt 5 Nov: `eval_sites_aoi.geojson` 662 sites, 4.4 MB; `html/aoi_eval_sites_map.html` regenerated (uncommitted). Old files in
  `CSDA_eval/sites/backup_before_sli_fusion_2026-11-05/`. After the write, the sheet's 41 rows were edited to `Program Use = SLI`, `Source = NASA`,
  so `new_eval_sites_rows_checked.csv` no longer matches those two columns; the sheet rules. Simplify step selects rows by `aoi_id`.
- `csda_eval_sites_map.ipynb`: point sites drawn as 1 km circles (Leetown has no `aoi_shape`; the notebook had not run since it was added).
  Run on ADAPT needs `PROJ_LIB`, `PROJ_DATA`, `GDAL_DATA` from the R kernel and pandoc on the path; `CSDA_ONLY = FALSE` for this map.
- CSDA files had drifted since their last builds (13 Oct, 24 Jun), not from this work: all 165 CSDA site geometries unchanged. New corner
  reflector row `Atlantic Doldrums 1`; 14 corner reflector rows have no geometry (e.g. `Pacific Doldrums 1`: `cr:lat` -94.36, `cr:lon` 0, looks
  swapped). `onramp2` lost `Konya` (now `Konya-airport` / `Konya-city`) and Railroad Valley changed shape.
- Open: check maps before commit (illustrative boxes,
  ARD tiles). Raise with USGS: only 3 of 21 perimeters fall inside the ARD tiles. Backup of the tab before the edit:
  `specs/backups/evaluation_sites_before_sli_fusion_2026-11-05.csv`.

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
  Write-ups: `docs/notes/SPOT6_DUPLICATE_ACQUISITION_ID_FIX.md`, `docs/notes/SPOT6_DUPLICATE_ACQUISITION_ID_POSTDISSOLVE_FIX.md`.
### 2026-08-27 · Sensor profiles added (`f0fd64c`); 2026-08-25 · multi-site footprint bug fix
### 2026-07-01 · `csdalib` refactored for footprinting; HTML map of footprints
### 2026-02 to 2026-03 · First footprint and summary notebooks; R library for VHR metadata analysis

---

## 6 · Evaluation results, RadCalNet and spectral response

### 2026-11-06 · RSR database: added sensors
- New curves in `CSDA_eval/results/evaluation_results_db/rsr/added/` (README and `build_added_rsr.py` there), appended to both `csda_rsr_curve_data.csv` copies (backups `*_pre_added_2026-11-06.csv`). The database files stay off GitHub.
- Measured: MODIS, VIIRS, Sentinel-3 OLCI and SLSTR (Pyspectral v1.6.1, CC-BY-4.0, credited on the page); Landsat 5 TM and 7 ETM+ (GFZ pyrsr, Apache-2.0).
- Modeled, not measured: Tanager (426 bands) and Pixxel Firefly (135 per satellite), as Gaussians from centers and FWHM in delivered products. Files are named `gaussian_*`; the panels say *modeled* and leave the band table.
- Band center now ignores response below 5% of the peak (VIIRS M1 read 422 nm from an out-of-band tail; now 410.5). Sentinel-2 values did not move.
- `build_rsr_db.ipynb` reads `rsr/added/` and keeps band names outside `band_order`. Snippet tested in R; the notebook itself not rerun. Its plots show those bands as NA.
- **Not found (29 constellations):** no public curves for Hydrosat VanZyl, EarthDaily, Satlantis GEISAT-P and HORACIO, OroraTech, OSK GHOSt and GHOSt-6, ImageSat EROS-A, B, C2, C3 and Runner-1, HotSat, FireSat, Pelican Gen 1 and 2, Kuva. Also none reachable for EnMAP, DESIS, MERIS, PROBA-V, GCOM-C (NWP SAF has only its two thermal channels), ADEOS, ADEOS-II, ALOS, ALOS-3, IKONOS, WorldView-1, WorldView-4. None were invented from band edges.
- Leads: EarthDaily says its Science product metadata holds spectral response functions; OSK's SPIE 2024 calibration paper; Apollo Mapping's "Maxar Constellation Spectral Response Values" (blocks automated access) for WorldView-1, WorldView-4 and maybe IKONOS; any EnMAP L2A scene for band centers and FWHM.

### 2026-11-06 · Vendor Specs: one pinned set of filters
- Sector, Status, Highlight, Find, Color by and the owner key now sit above the tabs and stay on screen with them (static on phones and very short windows). Tiles moved above the bar.
- Every tab reads the same filters: Spectral Response through `RSR_GROUPS` (panel to dashboard groups), replacing its own constellation picker; the Edit record through each sensor's group, replacing its own Find. Core fields and Automated checks stay whole-database. Color by is off on tabs without owner colors.
- Revisit moved out of Coverage to its own tab, so `#revisit` links open it again; Coverage is now the swath map.
- Find takes comma-separated names. Chart-specific settings (revisit view, wavelength range, AOI, Map / Panels) stay with their charts.

### 2026-11-06 · Vendor Specs: Spectral Response tab (`lib/vendor_specs_dashboard.html`)
- Panels per constellation, the notebook's band colors, thin lines over faint fills. Controls: wavelength range, response axis (0.25–1 as in the notebook, or 0–1), constellations, band key; hover gives sensor, band, response, center and FWHM. A table lists band centers and widths.
- `rsr_curves()` reads `RSR_CSV` (`CSDA_eval/results/csda_rsr_curve_data.csv`, 10 Sep) into 416 curves, simplified to within 0.3 nm or 0.003 response; center and FWHM come from the full curves. The tab hides if the file is not there (it is not on the Hub). Owners and Sentinel-2 are named as on the dashboard.
- All RSR curves cleared for the public page by Paul, 2026-11-06. They go in as numbers.
- Data issues found, none changed in the source:
  - Two copies of the file: `evaluation_results_db/rsr/` (6 Oct, what the notebook writes) adds newsat51-52 but lacks WV3 SWIR, Cirrus and thermal bands. Shared rows match.
  - SuperDove has two bands named `Green` (peaks 528 and 557 nm); the tab splits them into Green 1 and Green 2. The notebook plots them as one zigzag line.
  - SkySat 1-13 are not normalized (peaks 0.27-0.44); SkySat 14-19 reach 1.0.
  - Landsat thermal: `TIRS-2` wavelengths are ~10x too small (980-1300 nm) and `OLI-1` has a TIR1 band at 9000-14000 nm. Thermal is left out of the tab.

### 2026-11-06 · Vendor Specs: footprint map (`lib/vendor_specs_dashboard.html`, trial)
- *Cross-track swath width* has a View switch: **Map** (new, default) and **Panels** (unchanged). Map: Leaflet 1.9.4 from unpkg (pinned with SRI);
  one square per constellation at ground scale, degrees per km taken at the center latitude; Esri World_Imagery or World_Terrain_Base, World_Hillshade and World_Light_Gray_Base with its label layer. Past a layer's last real zoom Esri serves a "Map data not yet available" tile, so each is capped and stretched beyond that: imagery 17, terrain 9, hillshade 13, light gray 16 (sampled at 50-60 evaluation sites, 2026-11-06). Credits taken from each service.
  Follows the shared filters, Color by and Highlight. Includes swaths wider than `footprint_max_km`, which Panels lists as text.
- Keyword box picks one of the 662 evaluation sites (`eval_sites()` reads `sites/eval_sites_aoi.geojson`; default Railroad Valley). Backgrounds are a Leaflet layers list.
- **Revisit:** a systematic imager collects its whole swath on every pass, so `revisit()` now counts the full swath in the ≤20° view too (it had been cut to the central 20°). 13 sheet rows change, none in full agility: MODIS 2.61 → 0.58 d at 0°, also VIIRS, Sentinel-3, MERIS, PROBA-V, ADEOS, ADEOS-II, GCOM-C. MODIS is Terra + Aqua together; one satellite alone is ~1.16 / 0.88 / 0.67 d at 0° / 40° / 60°.
- **EnMAP** added as row 89 (batch `enmap_2026-11-06`, 27 cells, `specs/public_check_2026-11-06_enmap.csv`). Sources: enmap.org spec sheet, eoPortal; 224 bands from DLR's tutorial (eoPortal says 228; the spec sheet gives no count). Revisit Time left empty: no published figure for <20°. `record_edits` now counts rows the record added when placing a new row.
- Colors: Vantor gray → `#00B8D9`, DLR `#00441B` (`csda_specs_multispec_smry.ipynb` still has Vantor gray). Sector chips show swatches only when *Color by* = Sector.
- **Firefly:** Ffly 01-03 (sheet rows 89-91) were wrong and redundant; removed from the sheet by hand. Their 81 cells are taken out of `specs/edits_log.csv` and the batch CSV, the one exception to the append-only record (the old rows are in git; the sheet's *Edit log* tab still lists them). Firefly now counts 3 satellites: ≤20° revisit 2.03 / 1.55 / 1.19 d at 0° / 40° / 60° (was 1.02 / 0.77 / 0.60).
- MODIS stays as Terra + Aqua combined (checked with Paul).
- AOIs: the chosen AOI is shaded behind the swath squares (polygons from `sites/eval_sites_aoi.geojson`, simplified to 1% of each extent; page now ~880 KB). Section renamed *Cross-track swaths with evaluation AOIs*, box *Evaluation AOI*, tile *sensors in database*; the *Preliminary* sentence is gone from the subtitle.
- **Tabs reorganized** by the question each answers: *Imaging Specs* (footprint vs. detail, key specs), *Coverage* (swath map, revisit, method), *Launches & Orbits*, *Data Table*, *Database Quality*. Replaces Comparison and Revisit; old `#revisit` links open Coverage. The map starts on the first Coverage visit.
- **Open:** sheet not written: `specs/apply_edits.gs` holds EnMAP's 27 cells, `specs/write_revisit.gs` the new revisit values. Uncommitted.

### 2026-11-04 · Results exchange guide and templates (`eval_results_exchange/`, draft v0.1)
- `Suggested_Best_Practices_Compiling_Joint_Evaluation_Results.md` + 7 results templates and `methods_template.csv`. Existing column names kept where notebooks use them;
  new: `agency`, `team`, `method_id`, `status`, `product_id`, `radiometric_type`, `reference_name`, uncertainty columns.
- Design: delivery files are owned by each agency and never overwritten; common tables are rebuilt from them, never edited.
- Checked: `gain` = measured / reference at normalized view geometry. All templates pass `read_evaluation_files`.
- Needed before use: `build_eval_results_db.ipynb` must take the new file names and abscal / tempstab shape (one row per reference).
- Found in the database: `acq_id` empty in radiometric tables; geometric dates have no time; BBR pooled to `All_geometric`; combined
  `product_level` values; geometric build hard-coded to `09012026` files (Satellogic geometric not included).
- All 14 ESA sites (`ESA_misc_20260924` tab) are in `csda_sites_aoi.geojson` under the same names, with geometry.
- `evallib.r`: `read_evaluation_files` takes `site_name` from the sites database (ignoring case, spaces, hyphens and underscores) after the
  crosswalk, instead of title-casing everything (`PICS Libya-4` became `Pics Libya-4`; `WLEF` would have become `Wlef`). Unmatched names
  stay title case and are reported. Old vs new on all files in the build: only `Pics Libya-4` -> `PICS Libya-4` changes. The database
  still has the old name until the next build.

### 2026-11-04 · Timeline: Highlight, Find and Joint Activities lane (`lib/timeline_template.html`)
- **Highlight** dims all but one evaluation or activity type; **Find** hides activities that do not match (activity, notes,
  status, dates, link labels), in the cards, chart and list. Filter bar sticks to the top on scroll.
- **Joint Activities** events are converted to activities in the template, so they get a filter chip, card, lane, status
  pills, list rows and tooltips like any evaluation. Picking a vendor chip now hides them, and the gray event bands behind
  the chart show only with the Joint Activities lane.
- Augmentation summary tables moved to `html/augmentation/` (GitHub Pages), replacing the claude.ai page links.

### 2026-11-03 · Vendor Specs: Pixxel Firefly rows added
- Firefly was never in the Vendor Specs tab (not in the 2 Nov snapshot or any saved notebook output since Feb 2026); it
  was only in the acquisition-request tab (gid 900814542, 16 FF01 rows).
- 6 rows, one per satellite: FF01–FF03 (launched 2025-01-14) and Ffly 01–03 (2025-08-26, SpaceX NAOS), Pixxel's own
  designations. 27 fields from the CSDA vendor page first (590 km SSO, 40 km swath, 5.36 m GSD, ±30° slew, 135 bands
  470–900 nm, 10-bit, pushbroom, revisit "1 - 2 days"), then Pixxel docs (names, 4–11.5 nm bandwidths), Pixxel news
  (second launch), skyrocket.de (first launch date, 60 kg); period and size class computed. Where sources differ
  (Pixxel docs: 589 km, 38 km, ±20°, revisit <7 / <4 d) it is in the cell note and the row's Notes. Hypersp Min/Max in nm,
  as in the other hyperspectral rows. assessment status left empty.
- `record_edits` now takes rows below the last sheet row as new rows (before = empty, label from the proposed
  Constellation/Platform + Sensor Name); `apply_edits` adds them until the sheet has them. The Apps Script writes number
  ranges such as `1-2` as text so Sheets does not turn them into dates. Mock test: 162 cells written, rows 86–91 created,
  nothing else changed.
- Revisit (≤20°, whole year): 1.0 / 0.77 / 0.60 d at 0° / 40°N / 60°N; in `specs/revisit_estimates.csv` and
  `write_revisit.gs` (run after `applyEdits`, so the rows exist). Display name *Pixxel Firefly* (notebook `LABELS`).

### 2026-11-03 · Vendor Specs: revisit estimates into the sheet; Revisit tab grouping
- **Sheet columns** (`vs.revisit_sheet_columns`, `vs.revisit_apps_script`, notebook section 6): `Revisit est. 0° / 40°N /
  60°N (days, ≤20° view)`, the same for `full agility`, and `Revisit est. notes` (date, settings, satellites counted,
  assumptions). Whole-year values; a constellation's value on each of its current rows (71 of 84 rows); retired / planned
  rows of a current constellation get only a note; `no access` = orbit never reaches the latitude. Record:
  `specs/revisit_estimates.csv`. `specs/write_revisit.gs` (previewRevisit / writeRevisit) finds columns by header and
  appends missing ones after the last header (CY–DE, only into empty columns), matches rows by Sensor Name +
  Constellation/Platform, and logs one row per column in *Edit log*. Tested on a mock of the sheet: nothing else
  changes, a second run changes nothing, moved rows still match.
- **Dashboard**: title *Revisit time (estimated)…*; sheet-value tick removed; markers take the *Color by* color
  (data owner or sector), shape = latitude; *Group rows*: none / sector / data owner. Byline under the page title.

### 2026-11-03 · Vendor Specs: revisit time by latitude (Revisit tab)
- **Why simulate**: the sheet's *Revisit Time (days, < 20° onva)* mixes vendor figures at full agility (Pléiades 1 d,
  Legion 0.5 d) with single-satellite repeat cycles (Landsat 16 d), so it cannot be compared across constellations.
- **Method** (`vs.revisit`, `vs.orbit_passes`, `vs.orbit_inputs`): circular orbit at the sheet altitude with J2 node drift,
  one year in 2-minute steps, sites on 36 longitudes at 0°, 40°N, 60°N. A pass counts when the site is within reach
  (half swath + agility), within the view-angle limit (20° or full agility) and the sun is ≥ 10° high. Revisit = 1 / passes
  per day, satellites spread evenly; current satellites only. One simulation per distinct orbit (~2–3 min for all groups);
  60 s and 120 s steps give the same pass counts.
- **Latitudes**: 0° worst case for sun-synchronous orbits; 40°N our radiometric sites (23°S–46°N) and where vendors quote
  revisit; 60°N boreal, out of reach of mid-inclination orbits.
- **Inclination** is not in the sheet: sun-synchronous from altitude (Near polar rows treated the same); Legion 3–6 45°
  (Maxar) and EROS-C3 139.3° (tracking data) in `vs.ORBIT_INCLINATION`; EROS-C2 unknown, not plotted. An
  *Inclination (deg)* column in the sheet would be used first.
- **Agility not in the sheet**: wide-swath systematic mappers (swath ≥ 100 km) look at nadir; tasked or narrow-swath
  satellites are assumed able to point to 20° (shown in the ≤ 20° view only). Missing for SkySat C1/C2, EROS-C2/C3,
  Runner-1, Satellogic Mark II, HotSat, Tanager, Kuva, Hydrosat. Pelican and BlackSky Gen 3 have no altitude.
- **Results (whole year, ≤ 20°, days at 0° / 40° / 60°)**: Legion 1.0 / 0.5 / 2.0 (only LG-1/2 reach 60°); Pléiades Neo
  2.9 / 2.2 / 1.7; WorldView-3 5.9 / 4.5 / 3.4; Sentinel-2 3.1 / 2.4 / 1.8; Landsat 8/9 7.3 / 5.5 / 4.3;
  EROS-C3 5.6 / 1.2 / none. Vendor figures match the full-agility view, not ≤ 20°.
- **Dashboard**: Revisit tab between Comparison and Database Quality (shares the sector / status / highlight filters):
  one row per constellation, three markers (0° circle, 40° diamond, 60° triangle; one-hue blue ramp validated as
  ordinal in light and dark), the sheet value as a tick, a number column per latitude, view / season / sort toggles,
  hover for inputs. Notebook section 6; params `REVISIT_CAP_DEG`, `SUN_MIN_DEG`.

### 2026-11-02 · Vendor Specs: edits applied, with a record of every edit
- **Edit record** `specs/edits_log.csv`: one row per sheet cell (`edit_id`, `date`, `batch`, `cell` e.g. `CI2`, sensor,
  field, `before`, `after`, `source`, `source_url`, `note`). Batches are appended, never rewritten (`vs.record_edits`;
  a batch already in the record is not added twice). First batch: `public_check_2026-11-02` (86 proposals with
  `change = True` -> 140 cells; the GeoEye-1 "no change" row left out).
- **Into the Google Sheet**: `vs.apps_script` writes `specs/apply_edits.gs`, a Google Apps Script with the edits not yet in
  the sheet (notebook section 2). Paste into Extensions > Apps Script; `previewEdits` changes nothing, `applyEdits` writes a
  cell only if its column header matches the field and it still shows the `before` value, and appends one row per
  written cell to a sheet tab *Edit log*. Tested in headless Chromium against a mock built from the live sheet: 140
  written, a second run writes none. `apply_edits` treats `0.50` and `0.5` as the same value (the sheet drops zeros).
- 2026-11-03: first `applyEdits` run in the sheet wrote edits 1–130, then stopped at M77: the Orbit Type dropdown lists
  `mid-inclination LEO` (lowercase), so the case change to `Mid-inclination LEO` was rejected. That edit (M77, M78) is
  **withdrawn** (removed from the record, `change = False` with the reason in the batch CSV; ids not reused): record now
  138 cells, 130 in sheet, 8 to go. Script revised: a rejected cell is skipped and listed, the run goes on; the *Edit log*
  tab (columns logged, result, edit_id, batch, ...) lists every edit once (result *written*, or *already in sheet* for
  the 130 from the stopped run). Tested against a mock of the sheet after the stopped run, with the dropdown enforced.
- 2026-11-03: second run done; notebook re-run: **all 138 edits in the Google Sheet** (status *in sheet*), checks 45
  flagged cells in 33 rows. `specs/apply_edits.gs` kept as the script that was run.
- **Applied on top of the live sheet** (`vs.apply_edits`), so every view uses the edited values; status per cell:
  *applied (not yet in sheet)* (all 140 now), *in sheet* once the value is copied into the Google Sheet, *skipped: sheet
  changed* if the sheet holds a third value (the sheet wins). The Google Sheet itself is not changed yet.
- With the edits, checks: 45 flagged cells in 33 rows (was 75); core fields A–AS 57% filled.
- Notebook: new section 2 *Edits: record and apply* (`EDIT_LOG`, `EDIT_BATCHES`); checks are now section 3 and run on
  the edited values; plot asterisks mark only values still flagged by the checks.
- Dashboard: *Image footprints at true scale* renamed **Cross-track swath width** (also the static figure title); tab
  *Data quality* renamed **Database Quality**; its edits panel is now the **Edit record** (cell, sensor, field, before,
  after, status, source, note; searchable); tooltips list the edits applied to each constellation.

### 2026-11-02 · Vendor Specs: public-source check and interactive dashboard
- **Rule**: *Total Bands (MS)* counts the pan band (decided 2 Nov). QA check now flags rows that leave pan out (12: Legion,
  WorldView-2, BlackSky, FireSat, ALOS-3).
- **Public-source check** (`specs/public_check_2026-11-02.csv`, built by a script from the live sheet; not
  applied to the sheet): 87 proposed cell edits with current value, proposed value, source and note. Sources: CSDA vendor
  pages on science.nasa.gov (71; Airbus, Vantor, Planet, BlackSky, Satellogic, Hydrosat, OroraTech, Orbital Sidekick,
  Kuva, Satlantis, ImageSat), vendor / agency pages, 2 secondary, 5 computed. Main ones: OroraTech is thermal only
  (200 m TIR, 2 x 210 km swath; the 0.75 / 3 m GSDs were wrong); Satellogic Mark IV MS 0.99 m (0.7 m is Mark V);
  SuperDove / Dove-R MS 3.7 m and wider frames; Pelican Gen 1 pan 0.5 m; WorldView-3 17 bands; Hydrosat 7 VNIR + 2 LWIR;
  ImageSat EROS-C 0.43 / 0.86 m, 12.5 km; Kuva HF-1B launched 2025-06-23, 52 km, 22 bands; Satlantis VNIR 2 m, SWIR 7 m.
  The CSDA Vantor page's second "WorldView-1" table (0.41 / 1.65 m) looks like GeoEye-1. Not covered yet: launch dates,
  masses, altitudes for most vendors, EarthDaily, government sensors (except Landsat 7), columns AM on.
- **Dashboard** `html/vendor_specs.html` (template `lib/vendor_specs_dashboard.html`, `vs.write_dashboard`, notebook
  section 7): one self-contained page, no external libraries; scatter (black ring = has pan), aligned strips, footprints
  at true scale, completeness, checks, proposed edits, sortable table; hover tooltips with specs, open checks and
  proposed edits; sector / status / owner / text filters; light and dark (OS setting or toggle). Checked in headless
  Chromium (Playwright installed in the session scratchpad): no JS errors in light or dark. Not linked from the
  timeline yet.
- Static scatter (`plot_gsd_swath`) also draws the black pan ring.
- Dashboard: **launch timeline** (one mark per sensor row: launch date vs orbit altitude; shape = orbit type
  (sun-synchronous, mid-inclination / inclined, near-polar, not in sheet), size = satellite size class, color = sector,
  open = planned, line to the end date or today; labels = constellation group). Year-only launch dates are placed mid-year.
- Dashboard colors: **Color by** data owner (default) or sector; owner colors = the palette of
  `csda_specs_multispec_smry.ipynb` (Set1 + Dark2, BlackSky black, US Agency blue; `vs.AFFILIATION_COLORS`), plus
  OrbitalSideKick #7570B3 (new since; further new owners take `EXTRA_COLORS`). Shared color key under the filters (click an
  owner to highlight it); thin marker outlines keep ESA yellow and BlackSky black visible in light and dark. 17+ hues
  exceed the dataviz palette's categorical cap: kept for familiarity, palette may change later.
- Dashboard retitled *CSDA Vendor Specification Database: optical constellation comparison*; two tabs: **Comparison**
  (2 tiles, filters, color key, charts, table view) and **Data quality** (completeness, checks and proposed-edits tiles
  and panels, own search box; deep link `#quality`), so results and error checking are kept apart.

### 2026-11-02 · Vendor Specs database: QA, update loop, constellation comparison (`csda_specs_compare.ipynb`)
- Sheet `13MrpqFt...` tab *Vendor Specs* (gid 1094438485), read live; 84 sensor rows. `lib/vendor_specs.py`: `load`,
  `qa_checks`, `constellations` (sensors with the same owner, GSD, swath and band count merged, e.g. Legion LG-1..6,
  VIIRS on 4 platforms), `extraction_prompt` / `compare_extracted` (NASA Chat loop for SharePoint vendor documents),
  `completeness`, and plots `plot_gsd_swath`, `plot_spec_strips`, `plot_footprints`, `plot_completeness`.
- QA (2 Nov): 76 suspect cells in 50 rows: shifted cells (FireSat, Satlantis HORACIO / GEISAT-P), Legion off-nadir GSD
  min < nadir and period 97 min vs ~95 min at 518 km, EROS-A Start Date looks like its End Date, status vocabulary
  ('Deorbited 2015'), Sentinel-3D 'Planned' after its launch date, empty Constellation for Kuva / OSK, and *Total Bands
  (MS)* counting pan for some rows but not others (definition needed). Suspected from outside knowledge, unverified:
  OroraTech GSDs copied from a VHR row, WorldView-3 MS bands 16 not 20, Pléiades Neo ~920 kg / 7 bands, Landsat 7 ETM+
  whiskbroom.
- Completeness: A–AS 56% filled; X, Y, AI, AR, AS empty for every sensor; R, S nearly empty; 25 of 84 rows have a
  Reference.
- Figures (`notebooks/vendor_specs_out/`, not in git): GSD vs swath (log-log, marker size = band bins, diagonals =
  pixels across the swath: most sensors sit at ~3,000-30,000), aligned GSD / swath / bands strips, footprints at true
  scale (small multiples, one km scale). Colors: dataviz reference palette slots 1-2 (commercial / government).

### 2026-11-02 · Timeline: Planet-Tanager TEM
- `evaluations_list` now has **Planet-Tanager** (9 panels; named like Vantor-Legion), after OroraTech. First entry:
  Planet & CSDA technical exchange meeting on Tanager (Fri 28 Aug 2026).
- HTML timeline (`lib/timeline_template.html`): the joint-events lane, legend and tooltips now read **Joint Activities**
  (was "Meetings, conferences & joint activities"); in the table, their evaluation and type columns too (were
  "Joint / all", "Meeting / joint activity").

### 2026-11-02 · Timeline: Evaluation Results dB and comparison sheet (joint events)
- *CSDA Evaluation Results dB*: bar from **1 Jul 2026** (started July; exact day not recorded) to the joint
  ESA-USGS-NASA summary (1 Apr 2027), marked ongoing. One database on ADAPT with all CSDA SME evaluation results,
  for comparing results across vendors; a key feature of the joint activities.
- *Shared joint evaluation comparison sheet with ESA & USGS*: shared **29 Oct 2026** (first entered as planned with a
  30 Nov placeholder; corrected the same day). Sheet started on ADAPT.
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

### 2026-11-10 · Page data in a separate repository
- The repo had grown to ~269 MB, mostly from regenerated page data. The archive pages' data files now live in
  `pahbs/csda_summaries_data` (working copy `~/code/csda_summaries_data`, env `CSDA_DATA_REPO`), published by GitHub
  Pages on the same site as these pages. `lib/data_repo.py`: `folder(name)` for builders, `push(message)` replaces the
  single commit (orphan branch, force push), so that repo never accumulates history. After a refresh:
  `python lib/data_repo.py push "what changed"`, then commit the rebuilt pages here.
- Pages embed `data_base` (the data repo URL) and fetch tab, footprint and density files from it.
- Old data stays in this repo's history; trimming that history is possible but not done.

### 2026-11-04 · Published maps moved to `html/`
- `footprints_csda_map.html`, `aoi_csda_sites_map.html`, `aoi_eval_sites_map.html` moved from `notebooks/`; the old
  `.../notebooks/*.html` URLs are now small redirect pages to the new ones (keep them). Updated: `footprint_CSDA_eval_all_data.ipynb` and `footprint_CSDA_eval_refactored.ipynb`
  (`out_html`, and the printed URL, which pointed at maap_tools), `csda_eval_sites_map.ipynb`, `csda_stac_search_legion.ipynb`,
  `timeline.ipynb`, and the 4 links in the `pahbs.github.io` site.
- `csda_eval_sites_map.ipynb` still saves in `notebooks/` (as `tmp_<name>`, so the redirect is not overwritten), then moves the map to `html/`: `saveWidget` to another folder leaves a
  `<name>_files` folder behind, which would be published.
- `html/eval_results_structure.html` moved too, still ignored (draft). `lib/timeline_template.html` and
  `lib/vendor_specs_dashboard.html` stay in `lib/`: they are templates, not published pages.

### 2026-11-04 · Repository cleanup
- Committed: library code (incl. `csdalib_download.py`, which the tracking notebooks need), 16 site request AOIs + `WV_request_AOIs.zip`,
  working notebooks, `footprints_csda_map.html`, SPOT6 write-ups, `run_distributed_global_search.sh`. Secret scan clean first.
- Kept out on purpose (public repo): `sites/OnRamp2_OrderTracking_*.xlsx`, Kuva overlap files, the Onramp2 site-request CSV,
  `eval_results_*` notebooks (draft results). `stac_search_tutorial-satellogic.ipynb` has signed URLs in its outputs.
- `.gitignore` is local only: `.git/info/exclude` excludes it, so the rules (incl. `*credentials*.json`) do not reach other clones.
- Removed from the repo (still in git history): `multistac_site_analysis.ipynb`, `results_legion_geometric.ipynb`,
  `results_legion_radiometric.ipynb`, `csdalib_refactored.py`.
- Left uncommitted for now: `.readthedocs.yaml` (points to ignored `docs/`), `sites/alaska_agb_validation_sites.geojson`.

### 2026-10-15 · Uncommitted state
- Modified: multistac libs, `stac_auth.py`, `stac_providers.yaml`, `staclib.py`, many notebooks; deleted:
  `results_legion_*.ipynb`, `csdalib_refactored.py`, `stac_collections.md`; untracked: new libs (`csdalib_v2.py`,
  `satellogic_*.py`, `searchlib.py`), notebooks, site files, `.readthedocs.yaml`.
- **Do not commit** `notebooks/s3_tmp_credentials.json`; consider ignoring `notebooks/__pycache__/` and data outputs
  (`*.gpkg`, `*.xlsx`, `stac_items_*.json`).
### 2026-02-25 · Repository created; README; Sphinx docs (`docs/`)

"""Resumable, tiled searches of the CSDA STAC API."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO
from shapely.geometry import shape


_THREAD_STATE = threading.local()


def create_global_tiles(
    tile_size_degrees: float = 30,
    bbox: tuple[float, float, float, float] = (-180, -90, 180, 90),
) -> list[dict[str, Any]]:
    """Create named, non-overlapping longitude/latitude tiles for a bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180 <= min_lon < max_lon <= 180):
        raise ValueError("bbox longitude bounds must be within [-180, 180]")
    if not (-90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox latitude bounds must be within [-90, 90]")
    if tile_size_degrees <= 0:
        raise ValueError("tile_size_degrees must be positive")

    columns = math.ceil((max_lon - min_lon) / tile_size_degrees)
    rows = math.ceil((max_lat - min_lat) / tile_size_degrees)
    tiles = []
    for column in range(columns):
        left = min_lon + column * tile_size_degrees
        right = min(left + tile_size_degrees, max_lon)
        for row in range(rows):
            bottom = min_lat + row * tile_size_degrees
            top = min(bottom + tile_size_degrees, max_lat)
            tiles.append(
                {
                    "id": f"tile_{column:03d}_{row:03d}",
                    "bbox": [left, bottom, right, top],
                }
            )
    return tiles


def _date_slices(
    start_date: str,
    end_date: str,
    months: list[int] | tuple[int, ...] | None,
) -> list[tuple[str, str, str]]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date must be on or before end_date")

    selected_months = sorted(set(months)) if months is not None else None
    if selected_months and any(month < 1 or month > 12 for month in selected_months):
        raise ValueError("months must contain values from 1 through 12")

    slices = []
    for year in range(start.year, end.year + 1):
        year_start = max(start, date(year, 1, 1))
        year_end = min(end, date(year, 12, 31))
        if selected_months is None or len(selected_months) == 12:
            slices.append(
                (f"{year}", year_start.isoformat(), year_end.isoformat())
            )
            continue

        for month in selected_months:
            month_start = date(year, month, 1)
            next_month = date(year + (month == 12), month % 12 + 1, 1)
            month_end = date.fromordinal(next_month.toordinal() - 1)
            interval_start = max(year_start, month_start)
            interval_end = min(year_end, month_end)
            if interval_start <= interval_end:
                slices.append(
                    (
                        f"{year}-{month:02d}",
                        interval_start.isoformat(),
                        interval_end.isoformat(),
                    )
                )
    return slices


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _cache_file(
    run_dir: Path, collection: str, period: str, tile_id: str
) -> Path:
    return (
        run_dir
        / "items"
        / _safe_name(collection)
        / _safe_name(period)
        / f"{tile_id}.geojson"
    )


def _get_catalog(stac_url: str, request_timeout: int, max_retries: int = 3) -> Client:
    """Thread-local STAC client, tolerant of pystac-client version differences."""
    client = getattr(_THREAD_STATE, "client", None)
    if client is not None:
        return client

    import inspect
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    headers = {}
    token = os.environ.get("CSDAP_TOKEN") or os.environ.get("EARTHDATA_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    supported = set(inspect.signature(StacApiIO.__init__).parameters)
    kwargs: dict[str, Any] = {}
    if "timeout" in supported:
        kwargs["timeout"] = request_timeout
    if "headers" in supported:
        kwargs["headers"] = headers
    if "max_retries" in supported:
        kwargs["max_retries"] = max_retries

    stac_io = StacApiIO(**kwargs)

    # Retry transport for versions without native max_retries support
    if "max_retries" not in supported and hasattr(stac_io, "session"):
        retry = Retry(
            total=max_retries,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        stac_io.session.mount("https://", adapter)
        stac_io.session.mount("http://", adapter)
        if headers:
            stac_io.session.headers.update(headers)

    client = Client.open(stac_url, stac_io=stac_io)
    _THREAD_STATE.client = client
    return client

def _write_checkpoint(path: Path, items: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    feature_collection = {
        "type": "FeatureCollection",
        "features": [item.to_dict() for item in items],
    }
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary_file:
            json.dump(feature_collection, temporary_file, separators=(",", ":"))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_checkpoint(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as checkpoint:
        data = json.load(checkpoint)
    if data.get("type") != "FeatureCollection" or not isinstance(
        data.get("features"), list
    ):
        raise ValueError(f"Invalid checkpoint: {path}")
    return data["features"]


def _run_search_slice(
    task: dict[str, Any],
    run_dir: Path,
    stac_url: str,
    request_timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    checkpoint = _cache_file(
        run_dir, task["collection"], task["period"], task["tile_id"]
    )
    if checkpoint.exists():
        try:
            features = _read_checkpoint(checkpoint)
            return {**task, "status": "cached", "count": len(features)}
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    interval = f"{task['start_date']}/{task['end_date']}"
    for attempt in range(max_retries + 1):
        try:
            catalog = _get_catalog(stac_url, request_timeout, max_retries)
            search = catalog.search(
                collections=[task["collection"]],
                bbox=task["bbox"],
                datetime=interval,
                max_items=None,
            )
            items = list(search.items())
            _write_checkpoint(checkpoint, items)
            return {**task, "status": "searched", "count": len(items)}
        except Exception as error:
            if attempt == max_retries:
                return {
                    **task,
                    "status": "failed",
                    "count": 0,
                    "error": f"{type(error).__name__}: {error}",
                }
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("Search retries exhausted unexpectedly")


def _feature_records(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for feature in features:
        geometry = feature.get("geometry")
        record = dict(feature.get("properties") or {})
        record["id"] = feature.get("id")
        record["collection"] = feature.get("collection") or record.get("collection")
        record["geometry"] = shape(geometry) if geometry else None
        if feature.get("bbox") is not None:
            record["bbox"] = feature["bbox"]
        for asset_key, asset in (feature.get("assets") or {}).items():
            record[f"asset_{asset_key}_href"] = asset.get("href")
            record[f"asset_{asset_key}_type"] = asset.get("type")
        records.append(record)
    return records


def load_search_results(run_dir: str | Path) -> gpd.GeoDataFrame:
    """Load all completed slice checkpoints from a search run."""
    run_dir = Path(run_dir)
    records = []
    for checkpoint in sorted((run_dir / "items").glob("*/*/*.geojson")):
        records.extend(_feature_records(_read_checkpoint(checkpoint)))

    if not records:
        return gpd.GeoDataFrame(
            {"id": [], "collection": [], "geometry": []},
            geometry="geometry",
            crs="EPSG:4326",
        )
    result = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    if "id" in result.columns:
        subset = [column for column in ("collection", "id") if column in result]
        result = result.drop_duplicates(subset=subset)
    return result.reset_index(drop=True)


def search_global_stac(
    collections: list[str],
    start_date: str,
    end_date: str,
    checkpoint_dir: str | Path,
    *,
    stac_url: str = "https://csdap.earthdata.nasa.gov/stac",
    bbox: tuple[float, float, float, float] = (-180, -90, 180, 90),
    tile_size_degrees: float = 30,
    months: list[int] | tuple[int, ...] | None = None,
    max_workers: int = 8,
    request_timeout: int = 90,
    max_retries: int = 2,
) -> tuple[gpd.GeoDataFrame, list[dict[str, Any]], Path]:
    """Search in resumable collection/date/tile slices and return all records.

    A successful slice, including a slice with zero results, is atomically
    saved as GeoJSON. Failed slices are reported and retried on the next run.
    The returned run directory is derived from the search settings, so changing
    them never silently mixes old and new results.
    """
    if not collections:
        raise ValueError("collections must contain at least one collection ID")
    if max_workers < 1 or request_timeout < 1 or max_retries < 0:
        raise ValueError("max_workers/timeout must be positive and retries non-negative")

    settings = {
        "stac_url": stac_url,
        "collections": sorted(set(collections)),
        "start_date": start_date,
        "end_date": end_date,
        "months": sorted(set(months)) if months is not None else None,
        "bbox": list(bbox),
        "tile_size_degrees": tile_size_degrees,
    }
    signature = hashlib.sha256(
        json.dumps(settings, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    run_dir = Path(checkpoint_dir) / signature
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    tiles = create_global_tiles(tile_size_degrees, bbox)
    date_slices = _date_slices(start_date, end_date, months)
    tasks = [
        {
            "collection": collection,
            "period": period,
            "start_date": interval_start,
            "end_date": interval_end,
            "tile_id": tile["id"],
            "bbox": tile["bbox"],
        }
        for collection in sorted(set(collections))
        for period, interval_start, interval_end in date_slices
        for tile in tiles
    ]

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_search_slice,
                task,
                run_dir,
                stac_url,
                request_timeout,
                max_retries,
            ): task
            for task in tasks
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            try:
                result = future.result()
            except Exception as error:
                task = futures[future]
                result = {
                    **task,
                    "status": "failed",
                    "count": 0,
                    "error": f"{type(error).__name__}: {error}",
                }
            results.append(result)
            if completed % 25 == 0 or completed == len(tasks):
                failed = sum(item["status"] == "failed" for item in results)
                print(
                    f"Completed {completed}/{len(tasks)} slices "
                    f"({failed} failed so far)"
                )

    return load_search_results(run_dir), results, run_dir
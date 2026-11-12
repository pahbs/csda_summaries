#!/usr/bin/env bash
set -euo pipefail

# Run the global CSDA STAC search across multiple accessible nodes by splitting the world
# into geographic longitude bands. Each node runs the same notebook logic on its
# assigned bbox, using all CPUs on that node via max_workers=$(nproc).
#
# Example usage:
#   lib/run_distributed_global_search.sh
#   NODE_LIST='node01 node02 node03' lib/run_distributed_global_search.sh
#   COLLECTIONS='planet' START_DATE='2020-01-01' END_DATE='2020-12-31' TILE_SIZE_DEGREES=30 \
#     lib/run_distributed_global_search.sh
#
# Notes:
# - This does not run the notebook file directly; it uses the same searchlib logic
#   that the notebook uses, but with a different bbox per node.
# - Each node writes its own checkpoint directories under ~/.csda_stac_cache/global_search_nodes/
# - Each per-slice checkpoint remains GeoJSON for resumable work units.
# - After workers finish, a merge step loads all checkpointed GeoJSON results and saves a final GeoParquet file with a .parquet extension.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # this script is in lib/
VENV_PATH="${VENV_PATH:-}"
ANACONDA_MODULE="${ANACONDA_MODULE:-anaconda}"
ENV_NAME="${ENV_NAME:-TF}"

NODE_LIST="${NODE_LIST:-node01 node02 node03}"
COLLECTIONS="${COLLECTIONS:-planet}"
START_DATE="${START_DATE:-1999-01-01}"
END_DATE="${END_DATE:-$(date +%F)}"
MONTHS="${MONTHS:-}"
TILE_SIZE_DEGREES="${TILE_SIZE_DEGREES:-20}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-90}"
MAX_RETRIES="${MAX_RETRIES:-2}"
CHECKPOINT_ROOT="${CHECKPOINT_ROOT:-$HOME/csda_stac_cache/global_search_nodes}"
MERGED_PATH="${MERGED_PATH:-$HOME/csda_stac_cache/global_search_nodes_merged/merged.parquet}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15}"

# shellcheck disable=SC2206
NODE_ARRAY=(${NODE_LIST})
NODE_COUNT=${#NODE_ARRAY[@]}
if [[ ${NODE_COUNT} -eq 0 ]]; then
  echo "No nodes configured. Set NODE_LIST='node01 node02 ...'" >&2
  exit 1
fi

if [[ -n "${VENV_PATH}" && ! -d "${VENV_PATH}" ]]; then
  echo "Requested Python environment not found at ${VENV_PATH}; trying to discover the correct env on the target node..." >&2
fi

mkdir -p "${CHECKPOINT_ROOT}"
mkdir -p "$(dirname "${MERGED_PATH}")"

# Quick connectivity check to make sure the target hosts are reachable before submitting work.
printf 'Checking accessible nodes...\n'
for host in "${NODE_ARRAY[@]}"; do
  if ssh ${SSH_OPTS} "$host" 'echo READY' >/dev/null 2>&1; then
    echo "  ${host}: READY"
  else
    echo "  ${host}: UNREACHABLE"
  fi
done

echo
read -r -p "Continue with distributed run across ${NODE_COUNT} node(s)? [y/N] " answer
case "$answer" in
  y|Y|yes|YES) ;;
  *) echo "Aborted."; exit 0 ;;
 esac

# Launch one bbox slice per node. Each node runs its own searchlib.search_global_stac call.
# longitude strip split: (-180..180) divided evenly across nodes.
pids=()
for idx in "${!NODE_ARRAY[@]}"; do
  host="${NODE_ARRAY[$idx]}"
  read -r west east < <(python3 - "$NODE_COUNT" "$idx" <<'PY'
import sys
n = int(sys.argv[1])
i = int(sys.argv[2])
west = -180.0 + i * (360.0 / n)
east = -180.0 + (i + 1) * (360.0 / n)
if i == n - 1:
    east = 180.0
print(f"{west} {east}")
PY
)

  run_dir="${CHECKPOINT_ROOT}/${host}_${idx}"
  mkdir -p "${run_dir}"
  rm -f "${run_dir}/.done" "${run_dir}/.failed"
  echo "Launching ${host} with bbox=(${west}, -90, ${east}, 90)"
  echo "  remote log: ${run_dir}/run.log"

  ssh ${SSH_OPTS} "$host" \
    env REPO_ROOT="${REPO_ROOT}" \
        VENV_PATH="${VENV_PATH}" \
        CHECKPOINT_ROOT="${CHECKPOINT_ROOT}" \
        COLLECTIONS="${COLLECTIONS}" \
        START_DATE="${START_DATE}" \
        END_DATE="${END_DATE}" \
        MONTHS="${MONTHS}" \
        TILE_SIZE_DEGREES="${TILE_SIZE_DEGREES}" \
        REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS}" \
        MAX_RETRIES="${MAX_RETRIES}" \
        ANACONDA_MODULE="${ANACONDA_MODULE:-anaconda}" \
        ENV_NAME="${ENV_NAME:-TF}" \
        WEST="${west}" \
        EAST="${east}" \
        HOST_TAG="${host}" \
        NODE_IDX="${idx}" \
        bash -s <<'REMOTE_SCRIPT' &
set -euo pipefail
ANACONDA_MODULE="${ANACONDA_MODULE:-anaconda}"
ENV_NAME="${ENV_NAME:-TF}"
MAX_WORKERS_PER_NODE="$(nproc)"
RUN_DIR="${CHECKPOINT_ROOT}/${HOST_TAG}_${NODE_IDX}"

mkdir -p "${RUN_DIR}"
rm -f "${RUN_DIR}/.done" "${RUN_DIR}/.failed"
exec > "${RUN_DIR}/run.log" 2>&1

echo "Starting remote work on ${HOST_TAG} with RUN_DIR=${RUN_DIR}"
echo "Using env ${ENV_NAME} and $(nproc) CPU cores"
cd "${REPO_ROOT}"
module load "${ANACONDA_MODULE}" 2>/dev/null || true

resolved_env="${VENV_PATH:-}"
if [[ -z "${resolved_env}" || ! -d "${resolved_env}" ]]; then
  for candidate in \
    "/panfs/ccds02/app/modules/miniforge/platform/x86_64/rhel/8.10/24.9.0/envs/${ENV_NAME}" \
    "/panfs/ccds02/app/modules/miniforge/platform/x86_64/rhel/8.10/24.9.0" \
    "$HOME/.conda/envs/${ENV_NAME}" \
    "/opt/conda/envs/${ENV_NAME}" \
    "/usr/local/anaconda3/envs/${ENV_NAME}" \
    "/usr/local/miniconda3/envs/${ENV_NAME}" \
    "$HOME/miniconda3/envs/${ENV_NAME}" \
    "$HOME/anaconda3/envs/${ENV_NAME}"; do
    if [[ -d "${candidate}" ]]; then
      resolved_env="${candidate}"
      break
    fi
  done
fi

if command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)" 2>/dev/null || true
  if conda env list 2>/dev/null | awk '{print $1}' | grep -Fxq "${ENV_NAME}"; then
    conda activate "${ENV_NAME}"
  elif [[ -n "${resolved_env}" && -f "${resolved_env}/bin/activate" ]]; then
    . "${resolved_env}/bin/activate"
  fi
elif [[ -n "${resolved_env}" && -f "${resolved_env}/bin/activate" ]]; then
  . "${resolved_env}/bin/activate"
else
  echo "Could not find a usable Python environment for ${ENV_NAME}. Try: module load anaconda; conda env list" >&2
  exit 1
fi

export PYTHONPATH="${REPO_ROOT}/lib:${PYTHONPATH:-}"

python - <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
sys.path.insert(0, str(repo_root / "lib"))

import searchlib

collections = [item.strip() for item in os.environ["COLLECTIONS"].split(",") if item.strip()]
months = None
if os.environ.get("MONTHS"):
    months = sorted({int(item.strip()) for item in os.environ["MONTHS"].split(",") if item.strip()})

bbox = (float(os.environ["WEST"]), -90.0, float(os.environ["EAST"]), 90.0)
checkpoint_root = Path(os.environ["CHECKPOINT_ROOT"]) / (os.environ["HOST_TAG"] + "_" + os.environ["NODE_IDX"])
checkpoint_root.mkdir(parents=True, exist_ok=True)

stac_gdf, search_report, checkpoint_run = searchlib.search_global_stac(
    collections=collections,
    start_date=os.environ["START_DATE"],
    end_date=os.environ["END_DATE"],
    checkpoint_dir=checkpoint_root,
    stac_url="https://csdap.earthdata.nasa.gov/stac",
    bbox=bbox,
    tile_size_degrees=float(os.environ["TILE_SIZE_DEGREES"]),
    months=months,
    max_workers=int(os.environ["MAX_WORKERS_PER_NODE"]),
    request_timeout=int(os.environ["REQUEST_TIMEOUT_SECONDS"]),
    max_retries=int(os.environ["MAX_RETRIES"]),
)

failed = sum(1 for row in search_report if row.get("status") == "failed")
print(f"NODE={os.environ['HOST_TAG']} BBOX={bbox} CHECKPOINT={checkpoint_run}")
print(f"UNIQUE_ITEMS={len(stac_gdf):,} FAILED_SLICES={failed}")
PY

touch "${RUN_DIR}/.done"
REMOTE_SCRIPT
  pids+=("$!")
done

echo
printf 'Distributed search tasks launched. Waiting for remote workers to finish...\n'
for pid in "${pids[@]}"; do
  wait "$pid"
done

# Final merge only after all remote workers have finished and produced their own checkpoint folders.
python3 - "$CHECKPOINT_ROOT" "$MERGED_PATH" "$REPO_ROOT" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
out_path = Path(sys.argv[2])
repo_root = Path(sys.argv[3])
run_dirs = []
for candidate in sorted(root.glob("*")):
    if candidate.is_dir() and (candidate / "manifest.json").exists():
        run_dirs.append(candidate)

if not run_dirs:
    raise SystemExit(f"No checkpoint directories found under {root}. Nothing to merge.")

import geopandas as gpd
import pandas as pd
sys.path.insert(0, str(repo_root / "lib"))

import searchlib

frames = [searchlib.load_search_results(run_dir) for run_dir in run_dirs]
non_empty = [frame for frame in frames if not frame.empty]
out_path.parent.mkdir(parents=True, exist_ok=True)

if not non_empty:
    empty = gpd.GeoDataFrame({"id": [], "collection": [], "geometry": []}, geometry="geometry", crs="EPSG:4326")
    empty.to_parquet(out_path, index=False)
    print(f"Wrote empty result to {out_path}")
    raise SystemExit(0)

merged = pd.concat(non_empty, ignore_index=True)
merged = merged.drop_duplicates(subset=[c for c in ("collection", "id") if c in merged.columns])
merged = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")
merged.to_parquet(out_path, index=False)
print(f"Merged {len(merged):,} unique STAC items into {out_path}")
PY

echo
printf 'Done. Final merged GeoParquet: %s\n' "${MERGED_PATH}"

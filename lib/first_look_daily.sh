#!/bin/bash
# Daily refresh of the archive first-look page (lib/first_look_daily.py), for cron:
#
#   0 3 * * * /home/pmontesa/code/csda_summaries/lib/first_look_daily.sh
#
# One run at a time (a run still going makes the next one exit), a log per day in $CACHE/logs (kept 60 days).
# Arguments are passed on, e.g. first_look_daily.sh --vendors kuva --no-push
set -u
CACHE=${FIRST_LOOK_CACHE:-/explore/nobackup/people/pmontesa/multistac/first_look_cache}
REPO=/home/pmontesa/code/csda_summaries
PYTHON=/panfs/ccds02/app/modules/jupyter/ilab/tensorflow-kernel/bin/python
mkdir -p "$CACHE/logs"
LOG="$CACHE/logs/$(date +%Y%m%d).log"
exec 9>"$CACHE/logs/.lock"
if ! flock -n 9; then
    echo "$(date '+%F %T') a previous run is still going; skipped" >> "$LOG"
    exit 0
fi
export USE_PYGEOS=0 PYTHONWARNINGS=ignore
cd "$REPO" || exit 1
"$PYTHON" -u lib/first_look_daily.py "$@" 2>&1 | grep --line-buffered -v 'PROJ: proj_create_from_database' >> "$LOG"
status=${PIPESTATUS[0]}
echo "$(date '+%F %T') exit $status (hostname $(hostname))" >> "$LOG"
find "$CACHE/logs" -name '*.log' -mtime +60 -delete
exit "$status"

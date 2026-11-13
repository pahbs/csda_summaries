#!/bin/bash
# Thumbnail pages for selection zips dropped into the candidate acquisitions folder (lib/candidate_watch.py), for cron:
#
#   */10 * * * * /home/pmontesa/code/csda_summaries/lib/candidate_watch.sh
#
# One run at a time (a long build makes the next runs exit), one log in the first-look cache's logs folder.
set -u
if [ "${1:-}" = "install" ]; then   # candidate_watch.sh install: add the cron line above (once) on this node
    line="*/10 * * * * /home/pmontesa/code/csda_summaries/lib/candidate_watch.sh"
    if crontab -l 2>/dev/null | grep -qF "$line"; then echo "already installed on $(hostname)"; else
        (crontab -l 2>/dev/null; echo "$line") | crontab - && echo "installed on $(hostname): $line"; fi
    exit 0
fi
LOGS=${FIRST_LOOK_CACHE:-/explore/nobackup/people/pmontesa/multistac/first_look_cache}/logs
exec 9>"$LOGS/.candidate_watch.lock"
flock -n 9 || exit 0
export USE_PYGEOS=0 PYTHONWARNINGS=ignore
cd /home/pmontesa/code/csda_summaries || exit 1
/panfs/ccds02/app/modules/jupyter/ilab/tensorflow-kernel/bin/python -u lib/candidate_watch.py 2>&1 \
  | grep --line-buffered -v -E 'PROJ: proj_create_from_database|previews: ' >> "$LOGS/candidate_watch.log"

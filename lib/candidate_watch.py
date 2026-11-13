"""Builds a thumbnail viewer page for each first-look selection .zip dropped into the candidate acquisitions folder on ADAPT.

    lib/candidate_watch.sh            # what cron runs every 10 minutes: lock, log, then this script
    python lib/candidate_watch.py     # once, by hand

SMEs save a selection on the Archive First Look page and drop the .zip into ROOT (any vendor subfolder). This finds zips without
a viewer page (or with a newer zip than its page) and builds <zip name>_thumbnails.html next to it with the project's vendor
logins (thumbnail_viewer.build), so no SME needs vendor API access. Next to each zip, <zip name>.status.txt says where it stands:
building, ready, or failed (with the reason; a failed zip is tried again only when it is replaced). Pages and status files are
made readable by the project group. Review zips (<selection>_review_...) and notebook checkpoints are left alone.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(os.environ.get("CANDIDATE_ROOT", "/explore/nobackup/projects/CSDA_eval/candidate_acquisitions"))
GROUP = "j1004"          # the CSDA_eval project group: everyone who can drop a zip can open its page
STALE_HOURS = 8          # a "building" status older than this is from a run that died: build again
MAX_CARDS = 600          # a page holds at most this many acquisitions (Candidate Acquisitions first, newest first): more
                         # makes a page of 100+ MB that takes hours to build and is slow to open


def say(*args) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def share(path: Path) -> None:
    try:
        os.chmod(path, 0o664)
        shutil.chown(path, group=GROUP)
    except OSError:
        pass   # a file someone else owns: leave it as it is


def waiting():
    """Selection zips that need a page: no page yet, a newer zip than its page, and not failed or building already."""
    for z in sorted(ROOT.rglob("*.zip")):
        if ".ipynb_checkpoints" in z.parts or "_review_" in z.name or z.name.startswith("."):
            continue
        page, status = z.with_name(f"{z.stem}_thumbnails.html"), z.with_name(f"{z.stem}.status.txt")
        if page.exists() and page.stat().st_mtime >= z.stat().st_mtime:
            continue
        if status.exists() and status.stat().st_mtime >= z.stat().st_mtime:
            text = status.read_text()
            if text.startswith("failed"):
                continue
            if text.startswith("building") and time.time() - status.stat().st_mtime < STALE_HOURS * 3600:
                continue
        if time.time() - z.stat().st_mtime < 60:   # still being copied in
            continue
        yield z, page, status


def main() -> int:
    os.umask(0o002)
    todo = list(waiting())
    if not todo:
        return 0
    import thumbnail_viewer   # only when there is work: it loads the catalogs' code
    for z, page, status in todo:
        rows = thumbnail_viewer.read_selection(z)[0]
        capped = len(rows) > MAX_CARDS
        cap_note = (f"Only the first {MAX_CARDS} of its {len(rows)} acquisitions are on the page (Candidate Acquisitions first, newest "
                    f"first): for all of them, save a narrower selection (fewer sites or months) and drop that in.\n") if capped else ""
        status.write_text(f"building since {time.strftime('%Y-%m-%d %H:%M')}: the thumbnail page will appear next to the zip\n" + cap_note)
        share(status)
        say("building", z)
        started = time.time()
        try:
            thumbnail_viewer.build(z, out=page, display=False, limit=MAX_CARDS if capped else None)
            share(page)
            status.write_text(f"ready {time.strftime('%Y-%m-%d %H:%M')}: open {page.name} from a notebook with "
                              f"thumbnail_viewer.show(page) to save the review next to the zip\n" + cap_note)
            say("ready", page, f"{time.time() - started:.0f} s")
        except Exception as error:
            traceback.print_exc()
            status.write_text(f"failed {time.strftime('%Y-%m-%d %H:%M')}: {type(error).__name__}: {error}\n"
                              "Replace the zip (or delete this file) to try again.\n")
            say("failed", z, error)
        share(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())

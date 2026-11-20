"""Builds a thumbnail page and a review notebook for each first-look selection .zip dropped into the candidate acquisitions folder.

    lib/candidate_watch.sh            # what cron runs every 10 minutes: lock, log, then this script
    python lib/candidate_watch.py     # once, by hand

SMEs save a selection on the Archive First Look page and drop the .zip into ROOT (any vendor subfolder). This finds zips without
a viewer page (or with a newer zip than its page) and builds <zip name>_thumbnails.html next to it with the project's vendor
logins (thumbnail_viewer.build), so no SME needs vendor API access. Next to each page it writes <zip name>_review.ipynb: the SME
opens it in JupyterLab and runs its one cell, which shows the page in the notebook, where Save review can write the kept CSV and
the review JSON next to the zip. (A page opened from the file browser is sandboxed by Jupyter and cannot save anything.) The
notebook needs no vendor access and nothing from this repository: only .tools/jupyter_page.py, kept up to date in ROOT.

Next to each zip, <zip name>.status.txt says where it stands: building, ready, or failed (with the reason; a failed zip is tried
again only when it is replaced). A zip in a folder this account cannot write to is listed in ROOT/CANNOT_BUILD.txt instead.
Everything this account owns in ROOT is made readable and writable by the project group. Review zips (<selection>_review_...)
and notebook checkpoints are left alone.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import time
import traceback
from pathlib import Path

LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))

ROOT = Path(os.environ.get("CANDIDATE_ROOT", "/explore/nobackup/projects/CSDA_eval/candidate_acquisitions"))
TOOLS = ROOT / ".tools"  # what the review notebooks import: a copy of lib/jupyter_page.py
GROUP = "j1004"          # the CSDA_eval project group: everyone who can drop a zip can open its page
STALE_HOURS = 8          # a "building" status older than this is from a run that died: build again
MAX_CARDS = 600          # a page holds at most this many acquisitions (Candidate Acquisitions first, newest first): more
                         # makes a page of 100+ MB that takes hours to build and is slow to open
ME = os.getuid()


def say(*args) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def share(path: Path) -> None:
    """Group read/write (and setgid on folders, so new files take the group) on what this account owns."""
    try:
        st = path.lstat()
        if st.st_uid != ME or stat.S_ISLNK(st.st_mode):
            return
        if path.group() != GROUP:
            shutil.chown(path, group=GROUP)   # first: a change of group clears the setgid bit
        want = 0o2775 if stat.S_ISDIR(st.st_mode) else 0o664
        if stat.S_IMODE(path.lstat().st_mode) != want:
            os.chmod(path, want)
    except (OSError, KeyError):
        pass


def share_all() -> None:
    share(ROOT)
    for path in ROOT.rglob("*"):   # checkpoints too: Jupyter saves there when someone else opens a notebook
        share(path)


def tools() -> None:
    """Keep ROOT/.tools/jupyter_page.py the same as lib/jupyter_page.py."""
    TOOLS.mkdir(exist_ok=True)
    src, dst = LIB / "jupyter_page.py", TOOLS / "jupyter_page.py"
    if not dst.exists() or dst.read_bytes() != src.read_bytes():
        shutil.copyfile(src, dst)
    share(TOOLS)
    share(dst)


def notebook(page: Path) -> Path:
    """<zip name>_review.ipynb next to `page`: instructions and one cell that shows the page where it can save."""
    stem = page.name[:-len("_thumbnails.html")]
    md = f"""# Thumbnail review: {stem}

1. **Click in the grey cell below and press Shift+Enter** (or the ▶ button above). The thumbnail page opens below the cell.
   Do this every time you open this notebook: Jupyter only shows the page once you run the cell.
2. Type your name in the page's *Reviewer* box, then go through the acquisitions: **K** keep, **D** drop (pick a reason),
   **U** undo, **←/→** next and previous. The **Timeline** at the top shows each site's acquisitions by sensor and date and
   updates as you decide: a red band means two Keeps from the same sensor at about the same time (set how close counts as
   the same time there). Click a dot to go to its card.
3. Click **Save review**. Two files appear in this folder, next to the selection zip:
   - `{stem}_review_<date>_<id>_kept.csv`: the acquisitions you kept (the purchase list)
   - `{stem}_review_<date>_<id>.json`: every decision and the reasons for the drops

   Save as often as you like. When you come back and run the cell again, the latest saved review is restored.

Opened straight from the file browser (double-click or *Open in New Browser Tab*), the `.html` page shows the same thumbnails but
**cannot save**: always review through this notebook.
"""
    code = ("import sys\n"
            f"sys.path.insert(0, {str(TOOLS)!r})\n"
            "import jupyter_page\n"
            f"jupyter_page.show({page.name!r})")
    nb = {"cells": [{"cell_type": "markdown", "id": "instructions", "metadata": {}, "source": md.splitlines(keepends=True)},
                    {"cell_type": "code", "id": "show-page", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": code.splitlines(keepends=True)}],
          "metadata": {"kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = page.with_name(f"{stem}_review.ipynb")
    out.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    share(out)
    return out


def zips():
    for z in sorted(ROOT.rglob("*.zip")):
        if ".ipynb_checkpoints" in z.parts or ".tools" in z.parts or "_review_" in z.name or z.name.startswith("."):
            continue
        yield z, z.with_name(f"{z.stem}_thumbnails.html"), z.with_name(f"{z.stem}.status.txt")


def waiting(z: Path, page: Path, status: Path) -> bool:
    """Does this zip need a page: none yet or a newer zip than its page, and not failed or building already?"""
    if page.exists() and page.stat().st_mtime >= z.stat().st_mtime:
        return False
    if status.exists() and status.stat().st_mtime >= z.stat().st_mtime:
        text = status.read_text()
        if text.startswith("failed"):
            return False
        if text.startswith("building") and time.time() - status.stat().st_mtime < STALE_HOURS * 3600:
            return False
    return time.time() - z.stat().st_mtime >= 60   # else still being copied in


def ready_text(page: Path, cap_note: str = "") -> str:
    stem = page.name[:-len("_thumbnails.html")]
    return (f"ready {time.strftime('%Y-%m-%d %H:%M')}: open {stem}_review.ipynb in JupyterLab and run its cell to review the "
            f"thumbnails and save the review next to the zip\n" + cap_note)


def main() -> int:
    os.umask(0o002)
    tools()
    blocked, todo = [], []
    for z, page, status in zips():
        if not os.access(z.parent, os.W_OK):
            if not page.exists():
                blocked.append(z)
            continue
        if waiting(z, page, status):
            todo.append((z, page, status))
        elif page.exists() and not page.with_name(page.name.replace("_thumbnails.html", "_review.ipynb")).exists():
            notebook(page)   # pages made before the notebooks, or by hand
            if status.exists() and status.read_text().startswith("ready"):
                status.write_text(ready_text(page))
            say("notebook for", page)
    note = ROOT / "CANNOT_BUILD.txt"
    if blocked:
        note.write_text("These zips have no thumbnail page because their folder is not writable by the project group.\n"
                        "Fix: in a JupyterLab terminal, run  chmod g+w <folder>  (as the folder's owner).\n\n"
                        + "".join(f"{z.relative_to(ROOT)}\n" for z in blocked))
        share(note)
        say("cannot write next to:", *[str(z) for z in blocked])
    elif note.exists():
        note.unlink()
    if todo:
        import thumbnail_viewer   # only when there is work: it loads the catalogs' code
    for z, page, status in todo:
        say("building", z)
        started = time.time()
        try:
            rows = thumbnail_viewer.read_selection(z)[0]
            capped = len(rows) > MAX_CARDS
            cap_note = (f"Only the first {MAX_CARDS} of its {len(rows)} acquisitions are on the page (Candidate Acquisitions first, newest "
                        f"first): for all of them, save a narrower selection (fewer sites or months) and drop that in.\n") if capped else ""
            status.write_text(f"building since {time.strftime('%Y-%m-%d %H:%M')}: the thumbnail page and its review notebook will "
                              "appear next to the zip\n" + cap_note)
            share(status)
            thumbnail_viewer.build(z, out=page, display=False, limit=MAX_CARDS if capped else None)
            share(page)
            notebook(page)
            status.write_text(ready_text(page, cap_note))
            say("ready", page, f"{time.time() - started:.0f} s")
        except Exception as error:
            traceback.print_exc()
            try:
                status.write_text(f"failed {time.strftime('%Y-%m-%d %H:%M')}: {type(error).__name__}: {error}\n"
                                  "Replace the zip (or delete this file) to try again.\n")
            except OSError:
                pass
            say("failed", z, error)
        share(status)
    share_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())

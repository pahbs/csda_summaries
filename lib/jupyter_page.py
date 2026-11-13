"""Show a local HTML page inside JupyterLab so that its script can save files on the server (thumbnail_viewer: reviews).

A page opened from JupyterLab's file browser is sandboxed by Jupyter (its /files/ responses carry "sandbox allow-scripts"), so its
script cannot write anything on ADAPT and cannot keep anything between visits. Shown in a notebook output instead, the page runs in
an iframe of JupyterLab's own origin: it reads and writes files through Jupyter's contents API, with the login already in place.

    import jupyter_page
    jupyter_page.show("/home/me/pmontesa/multistac/thumbnails/x_thumbnails.html")

The output holds only a small loader (the page itself is fetched from the server), so the notebook stays small. The page finds
how to reach the server in `window.frameElement.dataset.jupyter`: {base, root, token, xsrf, page}.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List


def candidates(path) -> List[str]:
    """Ways to spell `path` that the Jupyter server may see under its root: as given, resolved, and through any symlink in the home
    folder that leads to it (~/pmontesa -> /explore/nobackup/people/pmontesa). The page uses the first one under the server's root."""
    given = os.path.abspath(os.path.expanduser(str(path)))
    real = os.path.realpath(given)
    out = [given, real]
    home = Path.home()
    homes = list(dict.fromkeys([str(home), os.path.realpath(home)]))   # JupyterLab may report either (/home/me, /panfs/.../home/me)
    try:
        for entry in home.iterdir():
            if entry.is_symlink():
                target = os.path.realpath(entry)
                if real == target or real.startswith(target + os.sep):
                    out += [f"{h}/{entry.name}{real[len(target):]}" for h in homes]
    except OSError:
        pass
    return list(dict.fromkeys(out))


def in_kernel() -> bool:
    """Running in a Jupyter kernel (where show() has somewhere to draw)?"""
    try:
        from IPython import get_ipython
        shell = get_ipython()
        return shell is not None and "IPKernelApp" in shell.config
    except Exception:
        return False


LOADER = """<div id="%(id)s" style="font:13px system-ui,sans-serif;color:#555">Loading %(name)s…</div>
<script>
(async () => {
  const box = document.getElementById('%(id)s');
  const say = t => { box.textContent = t; };
  try {
    const node = document.getElementById('jupyter-config-data');
    const cfg = node ? JSON.parse(node.textContent) : {};
    const home = %(home)s;   // JupyterLab reports its root folder with the home folder as ~
    const root = (cfg.serverRoot || home).replace(/^~(?=\\/|$)/, home).replace(/\\/+$/, '');
    const base = cfg.baseUrl || '/', token = cfg.token || '';
    const xsrf = decodeURIComponent((document.cookie.match(/(?:^|; )_xsrf=([^;]*)/) || [])[1] || '');
    const page = %(paths)s.map(p => p === root ? '' : p.startsWith(root + '/') ? p.slice(root.length + 1) : null).find(p => p != null);
    if (page == null) return say('This page is outside the folders JupyterLab can open (' + root + '), so it cannot be shown here.');
    const headers = {}; if (xsrf) headers['X-XSRFToken'] = xsrf; if (token) headers.Authorization = 'token ' + token;
    const r = await fetch(base + 'api/contents/' + page.split('/').map(encodeURIComponent).join('/') + '?type=file&format=text&content=1',
      {headers, credentials: 'same-origin'});
    if (!r.ok) return say('Could not load ' + page + ' (' + r.status + ').');
    const frame = document.createElement('iframe');
    frame.style.cssText = 'width:100%%;height:%(height)s;border:1px solid #c3c2b7;border-radius:8px;background:#fcfcfb';
    frame.dataset.jupyter = JSON.stringify({base, root, token, xsrf, page});
    box.replaceChildren(frame);
    frame.srcdoc = (await r.json()).content;
  } catch (e) { say('Could not show the page here: ' + e); }
})();
</script>"""


def show(page, height: str = "88vh"):
    """Show `page` (an HTML file on this server) in the notebook output, able to save files beside its inputs."""
    from IPython.display import HTML, display
    page = Path(page)
    html = LOADER % dict(id=f"page-{uuid.uuid4().hex[:8]}", name=page.name, height=height,
                         home=json.dumps(str(Path.home())), paths=json.dumps(candidates(page)))
    display(HTML(html))

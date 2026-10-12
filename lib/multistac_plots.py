"""Plots for multistac results.

    import multistac, multistac_plots
    table = multistac.overview_by_month({"csda-cmr": None})        # catalog-wide
    table = res.by_month(["affiliation", "constellation", "sensor"])  # one search
    multistac_plots.plot_month_heatmap(table, color_by="affiliation")
"""

from __future__ import annotations

from typing import List, Optional, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import colormaps
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, LogNorm, Normalize, to_rgb
from matplotlib.patches import Rectangle

import multistac

MONTH_NAMES = multistac.MONTH_NAMES

# Single-hue sequential ramp (light = few, dark = many)
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
# Categorical hues in fixed order (assigned by first appearance, never cycled)
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
EMPTY_COLOR = "#f0efec"    # month with no acquisitions
SPAN_COLOR = "#dcd9d2"     # date range known, monthly counts not reported
SURFACE = "white"
INK = "#2b2b2b"
INK_MUTED = "#6b6b6b"
NON_KEY_COLUMNS = {"year", "total", *MONTH_NAMES}
OTHER_COLOR = "#8a8a85"    # groups beyond the 8 categorical hues fold into "Other"


def color_groups(weights: pd.Series) -> dict:
    """{group: hex}. Largest groups get the categorical hues in fixed order;
    if there are more than 8, the 7 largest keep a hue and the rest share
    OTHER_COLOR (label "Other") - hues are never generated or cycled."""
    order = list(weights.sort_values(ascending=False).index)
    if len(order) <= len(CATEGORICAL):
        return {g: CATEGORICAL[i] for i, g in enumerate(order)}
    colors = {g: CATEGORICAL[i] for i, g in enumerate(order[:len(CATEGORICAL) - 1])}
    colors.update({g: OTHER_COLOR for g in order[len(CATEGORICAL) - 1:]})
    return colors


def _human(n: float) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e4:
        return f"{n / 1e3:.0f}k"
    return f"{int(n):,}"


def _tick(t: float) -> str:
    return f"{t / 1e6:g}M" if t >= 1e6 else f"{t / 1e3:g}k" if t >= 1e3 else f"{t:g}"


def hue_ramp(hex_color: str, name: str = "hue") -> LinearSegmentedColormap:
    """One-hue ramp: pale tint -> the hue -> a deep shade of it."""
    rgb = np.array(to_rgb(hex_color))
    tint = rgb + (1 - rgb) * 0.62  # still distinct from the gray 'none' cells
    shade = rgb * 0.55
    return LinearSegmentedColormap.from_list(name, [tint, rgb, shade])


def _cmap(cmap: Union[str, LinearSegmentedColormap]):
    if cmap == "blue":
        return LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP)
    return colormaps[cmap] if isinstance(cmap, str) else cmap


def plot_month_heatmap(table: pd.DataFrame, rows: Optional[List[str]] = None,
                       color_by: Optional[str] = None, cmap="blue", log: bool = True,
                       start: Optional[str] = None, end: Optional[str] = None,
                       title: Optional[str] = None, show_totals: bool = True,
                       display_names: bool = True, max_rows: Optional[int] = 60,
                       spans: Optional[pd.DataFrame] = None,
                       figsize: Optional[tuple] = None, ax=None):
    """Timeline heatmap: one row per group, one cell per month.

    table : multistac.overview_by_month(), res.by_month(by=...) or
        multistac.month_table(gdf, by=...) output (key columns, year, Jan..Dec).
    rows : key columns defining a row, outermost first (default: all key
        columns of the table). The first is drawn as a bold group label when
        there are two or more, e.g. ["affiliation", "constellation", "sensor"].
    color_by : a key column whose values each get their own hue (fixed
        categorical order by size; beyond 8 values the smallest share a gray
        "Other"), e.g. "provider" or "affiliation". Cell darkness still
        encodes the count, on one shared scale.
    cmap : "blue" (default single-hue ramp) or any matplotlib colormap name,
        e.g. "viridis", "magma", "turbo". Ignored when color_by is set.
        Multi-hue maps like "turbo" read as categories and exaggerate small
        differences; prefer them for exploration rather than reporting.
    log : log color scale (counts often span several orders of magnitude).
    start, end : optional 'YYYY-MM' limits for the time axis.
    display_names : show provider display names (profile `display_name`).
    max_rows : keep only the rows with the most acquisitions (None = all); the
        subtitle says how many were left out.
    spans : multistac.overview() output. Collections without monthly counts
        (e.g. CSDA STAC) are drawn as a neutral band from first to last
        acquisition, labeled with the dates, total "n/a". Needs a
        provider/collection table (overview_by_month, by_month() default).
    Returns (fig, ax).
    """
    if table.empty and spans is None:
        raise ValueError("Empty table - nothing to plot")
    if table.empty:
        table = pd.DataFrame(columns=["provider", "collection", "year"] + MONTH_NAMES)
    keys = [c for c in table.columns if c not in NON_KEY_COLUMNS]
    rows = list(rows or keys)
    missing = [r for r in rows + ([color_by] if color_by else []) if r not in keys]
    if missing:
        raise ValueError(f"{missing} not in table columns {keys}; build the table with by=[...]")
    if color_by and color_by not in rows:
        raise ValueError(f"color_by='{color_by}' must be one of rows={rows}")

    table = table.copy()
    if display_names and "provider" in table:
        names = multistac.display_names()
        table["provider"] = table["provider"].map(lambda p: names.get(p, p))
    for r in rows:
        table[r] = table[r].fillna("unknown").astype(str)

    span_of = {}
    if spans is not None:
        if rows != ["provider", "collection"]:
            raise ValueError("spans= needs rows=['provider', 'collection']")
        sp = spans.dropna(subset=["first", "last"])
        names = multistac.display_names() if display_names else {}
        span_of = {(names.get(p, p), c): (pd.Timestamp(f), pd.Timestamp(l))
                   for p, c, f, l in zip(sp["provider"], sp["collection"], sp["first"], sp["last"])}

    long = table.melt(id_vars=rows + ["year"], value_vars=MONTH_NAMES,
                      var_name="month", value_name="count")
    long["date"] = pd.to_datetime(
        long["year"].astype(int).astype(str) + "-"
        + long["month"].map({m: f"{i:02d}" for i, m in enumerate(MONTH_NAMES, 1)}) + "-01")
    # Default axis: Jan of the first year with data .. the last month with data
    has = list(long.loc[long["count"] > 0, "date"])
    has += [d.to_period("M").to_timestamp() for f_l in span_of.values() for d in f_l]
    has = pd.Series(has) if has else long["date"]
    if has.empty:
        raise ValueError("Nothing to plot")
    t0 = pd.Timestamp(start) if start else pd.Timestamp(has.min().year, 1, 1)
    t1 = pd.Timestamp(end) if end else has.max()
    months = pd.date_range(t0, t1, freq="MS")
    long = long[(long["date"] >= months[0]) & (long["date"] <= months[-1])]

    row_keys = sorted({tuple(r) for r in table[rows].itertuples(index=False)} | set(span_of))
    grid = (long.pivot_table(index=rows, columns="date", values="count", aggfunc="sum", fill_value=0)
            if len(long) else pd.DataFrame())
    grid = grid.reindex(index=pd.MultiIndex.from_tuples(row_keys, names=rows), columns=months, fill_value=0)
    # Keep rows with counts in the window, or a known date range overlapping it
    window_end = months[-1] + pd.offsets.MonthEnd(1)
    in_window = {k for k, (f, l) in span_of.items() if f <= window_end and l >= months[0]}
    grid = grid[(grid.sum(axis=1) > 0) | grid.index.isin(list(in_window))]
    if grid.empty:
        raise ValueError("No acquisitions inside the time window")
    row_keys = list(grid.index)
    hidden = 0
    if max_rows and len(grid) > max_rows:
        keep = grid.sum(axis=1).nlargest(max_rows).index
        hidden = len(grid) - max_rows
        grid = grid.loc[[k for k in grid.index if k in set(keep)]]
        row_keys = list(grid.index)
    values = grid.to_numpy(dtype=float)
    totals = values.sum(axis=1)
    n_rows, n_cols = values.shape
    span_rows = [i for i, k in enumerate(row_keys) if totals[i] == 0 and k in span_of]

    if ax is None:
        figsize = figsize or (max(10, min(18, 4 + n_cols * 0.06)), 1.7 + 0.32 * n_rows)
        fig, ax = plt.subplots(figsize=figsize, facecolor=SURFACE)
    else:
        fig = ax.figure

    vmax = max(values.max(), 2)
    norm = LogNorm(vmin=1, vmax=vmax) if log else Normalize(vmin=0, vmax=vmax)
    mesh_kw = dict(edgecolors=SURFACE, linewidth=0.4)
    empty = LinearSegmentedColormap.from_list("empty", [EMPTY_COLOR, EMPTY_COLOR])
    no_counts = np.zeros(values.shape, bool)
    no_counts[span_rows, :] = True
    ax.pcolormesh(np.ma.masked_where((values > 0) | no_counts, np.zeros_like(values)), cmap=empty, **mesh_kw)
    cell_pt = ax.get_position().width * fig.get_figwidth() * 72 / n_cols
    for i in span_rows:
        f, l = span_of[row_keys[i]]
        x0 = max(0, (f.year - months[0].year) * 12 + f.month - months[0].month)
        x1 = min(n_cols, (l.year - months[0].year) * 12 + l.month - months[0].month + 1)
        ax.add_patch(Rectangle((x0, i + 0.2), x1 - x0, 0.6, facecolor=SPAN_COLOR, edgecolor="none", zorder=4))
        label = f"{f:%b %Y} – {l:%b %Y}"
        need = (len(label) * 7.5 * 0.55) / cell_pt + 1.5  # label width in cells, plus padding
        if x1 - x0 >= need or (x0 < need and n_cols - x1 < need):
            x, ha, color = (x0 + x1) / 2, "center", INK
        elif n_cols - x1 >= need:
            x, ha, color = x1 + 0.6, "left", INK_MUTED
        else:
            x, ha, color = x0 - 0.6, "right", INK_MUTED
        ax.text(x, i + 0.5, label, ha=ha, va="center", fontsize=7.5, color=color, zorder=5)

    if color_by:
        col = rows.index(color_by)
        raw_group = np.array([k[col] for k in row_keys])
        weights = pd.Series(totals, index=raw_group).groupby(level=0).sum()
        colors = color_groups(weights)
        row_group = np.array(["Other" if colors[g] == OTHER_COLOR else g for g in raw_group])
        groups = list(dict.fromkeys(g for g in weights.sort_values(ascending=False).index
                                    for g in (["Other"] if colors[g] == OTHER_COLOR else [g])))
        other_ramp = LinearSegmentedColormap.from_list("Other", ["#bdbcb6", OTHER_COLOR, "#3d3d3a"])
        scales = [(g, other_ramp if g == "Other" else hue_ramp(colors[g], g)) for g in groups]
        counted = {g for g, t in zip(row_group, totals) if t > 0}
        for g, ramp in scales:
            other = np.broadcast_to((row_group != g)[:, None], values.shape)
            ax.pcolormesh(np.ma.masked_where(other | (values <= 0), values), cmap=ramp, norm=norm, **mesh_kw)
        scales = [(g, ramp) for g, ramp in scales if g in counted]
    else:
        cm = _cmap(cmap)
        ax.pcolormesh(np.ma.masked_less_equal(values, 0), cmap=cm, norm=norm, **mesh_kw)
        scales = [(None, cm)] if totals.sum() > 0 else []

    # Year separators and labels
    years = sorted({d.year for d in months})
    for y in years:
        first = np.where(months.year == y)[0][0]
        if first > 0:
            ax.axvline(first, color=SURFACE, linewidth=2.5, zorder=3)
    step = 1 if len(years) <= 15 else 2
    ax.set_xticks([np.where(months.year == y)[0].mean() + 0.5 for y in years][::step])
    ax.set_xticklabels([str(y) for y in years][::step], color=INK, fontsize=9)
    ax.tick_params(axis="x", length=0, pad=4)

    # Row labels: inner keys joined; outermost key as bold group label
    grouped = len(rows) > 1
    labels = [" · ".join(k[1:]) if grouped else k[0] for k in row_keys]
    ax.set_yticks(np.arange(n_rows) + 0.5)
    ax.set_yticklabels(labels, color=INK, fontsize=9)
    ax.tick_params(axis="y", length=0, pad=4)
    ax.set_ylim(n_rows, 0)
    outer = [k[0] for k in row_keys]
    for i in range(1, n_rows):
        if outer[i] != outer[i - 1]:
            ax.axhline(i, color=SURFACE, linewidth=4)
    if grouped:
        offset = -(14 + 5.6 * max(len(l) for l in labels))  # clear the row labels
        for g in dict.fromkeys(outer):
            idx = [i for i, q in enumerate(outer) if q == g]
            ax.annotate(g, xy=(0, np.mean(idx) + 0.5), xycoords=("axes fraction", "data"),
                        xytext=(offset, 0), textcoords="offset points", ha="right", va="center",
                        fontsize=9, fontweight="bold", color=INK)

    if show_totals:
        for i, total in enumerate(totals):
            ax.annotate("n/a" if i in span_rows else _human(total), xy=(1, i + 0.5), xycoords=("axes fraction", "data"),
                        xytext=(6, 0), textcoords="offset points", ha="left", va="center",
                        fontsize=8.5, color=INK_MUTED)
        ax.annotate("total", xy=(1, 1), xycoords="axes fraction", xytext=(6, 4),
                    textcoords="offset points", ha="left", va="bottom", fontsize=8.5, color=INK_MUTED)

    for spine in ax.spines.values():
        spine.set_visible(False)

    # Color scale(s) below the plot, sized in inches so they don't depend on row count
    ax_h_in = ax.get_position().height * fig.get_figheight()
    bar_h, gap, top = 0.11, 0.24, 0.55
    left = 0.14 if color_by and scales else 0.0
    ticks = [t for t in (1, 10, 100, 1e3, 1e4, 1e5, 1e6) if t <= vmax] if log else None
    for i, (name, cm) in enumerate(scales):
        last = i == len(scales) - 1
        cax = ax.inset_axes([left, -(top + i * gap + bar_h) / ax_h_in, 0.4, bar_h / ax_h_in])
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cm), cax=cax, orientation="horizontal")
        cb.outline.set_visible(False)
        cb.ax.tick_params(labelsize=8, colors=INK_MUTED, length=0, pad=2)
        if ticks:
            cb.set_ticks(ticks)
            cb.set_ticklabels([_tick(t) for t in ticks] if last else [""] * len(ticks))
            cb.ax.minorticks_off()
        elif not last:
            cb.set_ticklabels([])
        if name is not None:
            cax.annotate(name, xy=(0, 0.5), xycoords="axes fraction", xytext=(-6, 0),
                         textcoords="offset points", ha="right", va="center", fontsize=8.5, color=INK)
    bottom = -(top + (len(scales) - 1) * gap + bar_h) / ax_h_in if scales else -0.35 / ax_h_in
    parts = ([f"Acquisitions per month{' (log scale)' if log else ''}", "gray = none"] if scales else [])
    parts += ["band = date range only (catalog reports no counts)"] if span_rows else []
    ax.annotate("  ·  ".join(parts),
                xy=(left, bottom), xycoords="axes fraction", xytext=(0, -20),
                textcoords="offset points", ha="left", va="top", fontsize=9, color=INK)

    span = f"{months[0]:%b %Y} - {months[-1]:%b %Y}"
    ax.set_title(title or "Acquisitions per month", loc="left", fontsize=12, color=INK, pad=22)
    note = f"  ·  top {n_rows} of {n_rows + hidden} rows shown" if hidden else ""
    counted_note = (f"{int(totals.sum()):,} acquisitions counted" if totals.sum() > 0 else "no counts")
    if span_rows:
        counted_note += f"  ·  {len(span_rows)} collections with dates only"
    ax.annotate(f"{span}  ·  {counted_note}{note}", xy=(0, 1), xycoords="axes fraction",
                xytext=(0, 6), textcoords="offset points", fontsize=9, color=INK_MUTED)
    return fig, ax


# --------------------------------------------------------------------------
# Small multiples helpers
# --------------------------------------------------------------------------

def _facets(gdf: pd.DataFrame, facet_by, max_facets: int):
    """[(label, sub-frame)], largest groups first, capped at max_facets."""
    if not facet_by:
        return [("", gdf)], 0
    cols = [facet_by] if isinstance(facet_by, str) else list(facet_by)
    g = gdf.copy()
    for c in cols:
        g[c] = g[c].fillna("unknown").astype(str)
    if "provider" in cols:
        names = multistac.display_names()
        g["provider"] = g["provider"].map(lambda p: names.get(p, p))
    sizes = g.groupby(cols).size().sort_values(ascending=False)
    keys = list(sizes.index[:max_facets])
    out = []
    for k in keys:
        k = k if isinstance(k, tuple) else (k,)
        sub = g[np.logical_and.reduce([g[c] == v for c, v in zip(cols, k)])]
        out.append((" · ".join(k), sub))
    return out, max(0, len(sizes) - max_facets)


# --------------------------------------------------------------------------
# Skyplots: sun and satellite positions as seen from the target
# --------------------------------------------------------------------------

def plot_skyplot(gdf: pd.DataFrame, facet_by=None, color_by: Optional[str] = None,
                 show_sun: bool = True, max_facets: int = 24, ncols: int = 4,
                 title: Optional[str] = None, panel_size: float = 3.4):
    """Polar skyplots of acquisition geometry (north up, clockwise).

    Radius = zenith angle (center = overhead, edge = horizon), labeled as
    elevation. Filled dots = satellite (sat_azimuth, sat_elevation), colored by
    `color_by` (e.g. "constellation"); small open circles = sun (sun_azimuth,
    sun_elevation). One panel per `facet_by` value(s), e.g. "site_name" or
    ["site_name", "constellation"]. Rows missing an azimuth or elevation are
    left out of that layer; the panel title gives both counts.

    Works on res.gdf or any multistac result GeoDataFrame. sat_elevation may be
    estimated from off_nadir (see column sat_elevation_source).
    Returns fig.
    """
    df = gdf.copy()
    for c in ("sat_azimuth", "sat_elevation", "sun_azimuth", "sun_elevation"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    has_sat = df[["sat_azimuth", "sat_elevation"]].notna().all(axis=1)
    has_sun = df[["sun_azimuth", "sun_elevation"]].notna().all(axis=1) & (df["sun_elevation"] > 0)
    df = df[has_sat | (has_sun if show_sun else False)]
    if df.empty:
        raise ValueError("No rows with satellite or sun azimuth + elevation")

    if color_by:
        df[color_by] = df[color_by].fillna("unknown").astype(str)
        if color_by == "provider":
            names = multistac.display_names()
            df[color_by] = df[color_by].map(lambda p: names.get(p, p))
        colors = color_groups(df.loc[df[["sat_azimuth", "sat_elevation"]].notna().all(axis=1), color_by]
                              .value_counts())
    facets, hidden = _facets(df, facet_by, max_facets)
    n = len(facets)
    ncols = min(ncols, n)
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(panel_size * ncols, (panel_size + 0.9) * nrows + 0.9),
                             subplot_kw={"projection": "polar"}, facecolor=SURFACE, squeeze=False)
    axes = axes.ravel()
    for ax, (label, sub) in zip(axes, facets):
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 90)
        ax.set_yticks([30, 60, 90])
        ax.set_yticklabels(["60°", "30°", "0°"], fontsize=7, color=INK_MUTED)
        ax.set_rlabel_position(135)
        ax.set_xticks(np.radians([0, 90, 180, 270]))
        ax.set_xticklabels(["N", "E", "S", "W"], fontsize=8, color=INK)
        ax.grid(color="#dddddd", linewidth=0.6)
        ax.spines["polar"].set_color("#cccccc")
        sat = sub.dropna(subset=["sat_azimuth", "sat_elevation"])
        sun = sub[(sub["sun_elevation"] > 0)].dropna(subset=["sun_azimuth", "sun_elevation"]) if show_sun else sub.iloc[:0]
        if len(sun):
            ax.scatter(np.radians(sun["sun_azimuth"]), 90 - sun["sun_elevation"], s=14,
                       facecolors="none", edgecolors=INK_MUTED, linewidths=0.7, alpha=0.7, zorder=3)
        if len(sat):
            c = sat[color_by].map(colors) if color_by else CATEGORICAL[0]
            ax.scatter(np.radians(sat["sat_azimuth"]), 90 - sat["sat_elevation"], s=16, c=c,
                       edgecolors=SURFACE, linewidths=0.4, alpha=0.85, zorder=4)
        ax.set_title(label, fontsize=9.5, color=INK, pad=16, loc="center")
        ax.annotate(f"satellite n={len(sat):,}   sun n={len(sun):,}", xy=(0.5, -0.12), xycoords="axes fraction",
                    ha="center", fontsize=7.5, color=INK_MUTED)
    for ax in axes[n:]:
        fig.delaxes(ax)

    from matplotlib.lines import Line2D
    handles = []
    if color_by:
        shown = {}
        for g, col in colors.items():
            shown.setdefault("Other" if col == OTHER_COLOR else g, col)
        handles += [Line2D([], [], marker="o", linestyle="", markersize=6, markerfacecolor=col,
                           markeredgecolor=SURFACE, label=f"{g}") for g, col in shown.items()]
    else:
        handles.append(Line2D([], [], marker="o", linestyle="", markersize=6, markerfacecolor=CATEGORICAL[0],
                              markeredgecolor=SURFACE, label="satellite"))
    if show_sun:
        handles.append(Line2D([], [], marker="o", linestyle="", markersize=5, markerfacecolor="none",
                              markeredgecolor=INK_MUTED, label="sun"))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 1.0), ncol=min(len(handles), 8),
               frameon=False, fontsize=8.5, labelcolor=INK, handletextpad=0.3, columnspacing=1.2)
    note = f"  ·  {hidden} more panels not shown" if hidden else ""
    fig.suptitle((title or "Acquisition geometry (as seen from the target)") + note,
                 x=0.01, y=1.0 + 0.35 / fig.get_figheight(), ha="left", fontsize=12, color=INK)
    fig.text(0.01, -0.01, "Radius = elevation angle (center 90°, edge 0°). Dots: satellite"
             + (f", colored by {color_by}" if color_by else "") + ("; open circles: sun." if show_sun else "."),
             fontsize=8, color=INK_MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    fig.subplots_adjust(hspace=0.55)
    return fig


# --------------------------------------------------------------------------
# Global density maps (wraps staclib.plot_stac_acquisition_density)
# --------------------------------------------------------------------------

def plot_density_maps(gdf: pd.DataFrame, facet_by=None, max_facets: int = 8, ncols: int = 2,
                      sites=None, title: Optional[str] = None, panel_size=(9, 4.8), **kwargs):
    """Global acquisition density (Robinson, hexbin of footprint centroids).

    One map per `facet_by` value(s), e.g. "affiliation" or "constellation".
    Extra kwargs go to staclib.plot_stac_acquisition_density (bin_method,
    gridsize, cmap, vmax, ...). `sites`: optional GeoDataFrame to annotate
    (column 'Site Name' or pass site_name_col=). Returns fig.
    """
    import staclib
    facets, hidden = _facets(gdf, facet_by, max_facets)
    n = len(facets)
    ncols = min(ncols, n)
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(panel_size[0] * ncols, panel_size[1] * nrows),
                             facecolor=SURFACE, squeeze=False)
    axes = axes.ravel()
    kwargs.setdefault("show_sites", sites is not None)
    for ax, (label, sub) in zip(axes, facets):
        sub = sub[sub.geometry.notna()]
        staclib.plot_stac_acquisition_density(sub, sites_gdf=sites, ax=ax,
                                              title=f"{label}  (n={len(sub):,})" if label else None, **kwargs)
        ax.title.set_fontsize(11)
    for ax in axes[n:]:
        fig.delaxes(ax)
    parts = [title] if title else []
    parts += [f"{hidden} more groups not shown (max_facets={max_facets})"] if hidden else []
    if parts:
        fig.suptitle("  ·  ".join(parts), x=0.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------
# Distributions of acquisition properties by group
# --------------------------------------------------------------------------

DEFAULT_DISTRIBUTION_COLUMNS = ["cloud_cover", "gsd", "off_nadir", "sat_elevation", "sun_elevation"]
COLUMN_LABELS = {"cloud_cover": "Cloud cover (%)", "gsd": "GSD (m)", "off_nadir": "Off-nadir (°)",
                 "sat_elevation": "Satellite elevation (°)", "sun_elevation": "Sun elevation (°)",
                 "sun_azimuth": "Sun azimuth (°)", "sat_azimuth": "Satellite azimuth (°)",
                 "incidence_angle": "Incidence (°)"}


def plot_distributions(gdf: pd.DataFrame, by: str = "constellation",
                       columns: Optional[List[str]] = None, max_groups: int = 20,
                       title: Optional[str] = None):
    """Box plots of acquisition properties (columns) for each group (`by`).

    One panel per column, groups as rows (most acquisitions first), with n per
    group. Shows the inherent variation (cloud, GSD, view and sun angles)
    across vendors, constellations or sensors. Returns fig.
    """
    columns = columns or DEFAULT_DISTRIBUTION_COLUMNS
    df = gdf.copy()
    df[by] = df[by].fillna("unknown").astype(str)
    if by == "provider":
        names = multistac.display_names()
        df[by] = df[by].map(lambda p: names.get(p, p))
    for c in columns:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    columns = [c for c in columns if df[c].notna().any()]
    if not columns:
        raise ValueError("None of the columns have values")
    groups = list(df[by].value_counts().index[:max_groups])[::-1]
    fig, axes = plt.subplots(1, len(columns), figsize=(2.6 * len(columns) + 2.2, 0.32 * len(groups) + 1.6),
                             sharey=True, facecolor=SURFACE, squeeze=False)
    for ax, col in zip(axes[0], columns):
        data = [df.loc[df[by] == g, col].dropna().to_numpy() for g in groups]
        pos = [i for i, d in enumerate(data) if len(d)]
        bp = ax.boxplot([data[i] for i in pos], positions=pos, vert=False, widths=0.55, patch_artist=True,
                        showfliers=False, medianprops=dict(color=INK, linewidth=1.2),
                        whiskerprops=dict(color="#9a9a9a", linewidth=0.8), capprops=dict(color="#9a9a9a", linewidth=0.8))
        for box in bp["boxes"]:
            box.set(facecolor=BLUE_RAMP[2], edgecolor="none", alpha=0.9)
        ax.set_title(COLUMN_LABELS.get(col, col), fontsize=9.5, color=INK, loc="left")
        ax.grid(axis="x", color="#eeeeee", linewidth=0.6)
        ax.tick_params(colors=INK_MUTED, labelsize=8, length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    axes[0][0].set_yticks(range(len(groups)))
    counts = df[by].value_counts()
    axes[0][0].set_yticklabels([f"{g}  ({counts[g]:,})" for g in groups], fontsize=8.5, color=INK)
    fig.suptitle(title or f"Acquisition properties by {by}  (box = middle 50%, line = median, whiskers = 1.5 IQR)",
                 x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    return fig

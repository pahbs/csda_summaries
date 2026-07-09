import os
import glob
import datetime as dt
import io
import datetime

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np

# Map human-readable Site Names to short directory Site Codes
SITE_NAME_TO_CODE = {
    "Railroad Valley": "RVUS",
    "La Crau": "LCFR",
    "Gobabeb": "GONA",
    "Baotou": "BTCN",
    "Baotou Sand": "BSCN",
    "Gobabeb Sand": "GSCN"
}

# Reverse lookup for automatically converting codes back to descriptive titles
SITE_CODE_TO_NAME = {v: k for k, v in SITE_NAME_TO_CODE.items()}

def parse_multi_dataset_file(file_path):
    """Parses a RadCalNet file containing sequential data matrices by tracking

    wavelength resets and metadata blocks.
    """
    with open(file_path, "r") as f:
        lines = f.readlines()

    # We will hold blocks dynamically: (metadata_lines_list, spectral_lines_list)
    blocks = []
    current_meta = []
    current_spec = []

    last_wavelength = -1

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        parts = line_str.split()
        if not parts:
            continue

        # Check if row is a wavelength row (starts with a number)
        first_token = parts[0].replace(".", "", 1)  # handles potential floats
        if first_token.isdigit() and len(first_token) <= 4:
            current_wavelength = int(float(first_token))

            # STATE TRIGGER: Wavelength reset detected (e.g., 2500 -> 400)
            if current_wavelength < last_wavelength:
                # Save the completed block and initialize a new one
                blocks.append((current_meta, current_spec))
                current_meta = []
                current_spec = []

            current_spec.append(line_str)
            last_wavelength = current_wavelength
        else:
            # Skip static site position strings so they don't break our labels
            if any(
                line_str.startswith(x)
                for x in ["Site:", "Lat:", "Lon:", "Alt:"]
            ):
                continue
            current_meta.append(line_str)

    # Append the final block remaining at EOF
    if current_meta or current_spec:
        blocks.append((current_meta, current_spec))

    # --- Now parse the isolated blocks ---
    parsed_meta_dfs = []
    parsed_spec_dfs = []

    # Keep track of the master time strings from the VERY FIRST block
    master_timestamps = None

    for i, (meta_lines, spec_lines) in enumerate(blocks):
        # 1. Parse Metadata Lines
        meta_data = []
        meta_index = []
        for row in meta_lines:
            tokens = row.split("\t")
            if len(tokens) < 2:
                tokens = row.split()
            label = tokens[0].replace(":", "").strip()
            values = [t.strip() for t in tokens[1:] if t.strip() != ""]
            meta_index.append(label)
            meta_data.append(values)

        meta_df = pd.DataFrame(meta_data, index=meta_index)

        # 2. Extract or apply temporal headers
        if i == 0:
            # The first block contains the true Date/Time reference keys
            if (
                "Year" in meta_df.index
                and "DOY(U)" in meta_df.index
                and "UTC" in meta_df.index
            ):
                years = meta_df.loc["Year"].values
                doys = meta_df.loc["DOY(U)"].values
                utcs = meta_df.loc["UTC"].values

                master_timestamps = []
                for y, d, t in zip(years, doys, utcs):
                    try:
                        base_date = dt.datetime.strptime(f"{y}_{d}", "%Y_%j")
                        hour, minute = map(int, t.split(":"))
                        full_ts = base_date.replace(hour=hour, minute=minute)
                        master_timestamps.append(
                            full_ts.strftime("%Y-%m-%d %H:%M")
                        )
                    except Exception:
                        master_timestamps.append(f"Time_{t}")
            else:
                master_timestamps = [f"Col_{idx}" for idx in range(meta_df.shape[1])]

        # Assign unique names to columns based on the global timestamp timeline
        if master_timestamps and len(master_timestamps) == meta_df.shape[1]:
            meta_df.columns = master_timestamps

        # 3. Parse Spectral Matrix Data
        spec_str = "\n".join(spec_lines)
        spec_df = pd.read_csv(
            io.StringIO(spec_str), sep=r"\s+", header=None, index_col=0
        )
        spec_df.index.name = "Wavelength"

        if master_timestamps and spec_df.shape[1] == len(master_timestamps):
            spec_df.columns = master_timestamps

        parsed_meta_dfs.append(meta_df)
        parsed_spec_dfs.append(spec_df)

    return parsed_meta_dfs, parsed_spec_dfs


def compile_directory(directory_path, stage="input"):
    """Finds all stage files in directory and extracts them.

    Returns four master DataFrames:
      - reflectance_meta, reflectance_spectra (The core measurement blocks)
      - uncertainty_meta, uncertainty_spectra (The inner secondary parameter
      blocks)
    """
    stage_ext = stage.lower().replace(".", "")
    search_pattern = os.path.join(directory_path, f"*.{stage_ext}")
    file_list = sorted(glob.glob(search_pattern))

    if not file_list:
        print(f"No files matching *.{stage_ext} found.")
        return [pd.DataFrame() for _ in range(4)]

    all_ref_meta, all_ref_spec = [], []
    all_unc_meta, all_unc_spec = [], []

    for file_path in file_list:
        meta_blocks, spec_blocks = parse_multi_dataset_file(file_path)

        # Check if the file contained both dataset blocks
        if len(meta_blocks) >= 2:
            all_ref_meta.append(meta_blocks[0])
            all_ref_spec.append(spec_blocks[0])
            all_unc_meta.append(meta_blocks[1])
            all_unc_spec.append(spec_blocks[1])
        elif len(meta_blocks) == 1:
            # Fallback if a file only contains a single block
            all_ref_meta.append(meta_blocks[0])
            all_ref_spec.append(spec_blocks[0])

    # Combine chronologically side-by-side
    ref_meta = (
        pd.concat(all_ref_meta, axis=1, sort=False) if all_ref_meta else pd.DataFrame()
    )
    ref_spec = (
        pd.concat(all_ref_spec, axis=1, sort=False) if all_ref_spec else pd.DataFrame()
    )
    unc_meta = (
        pd.concat(all_unc_meta, axis=1, sort=False) if all_unc_meta else pd.DataFrame()
    )
    unc_spec = (
        pd.concat(all_unc_spec, axis=1, sort=False) if all_unc_spec else pd.DataFrame()
    )

    # Sort columns chronologically
    for df in [ref_meta, ref_spec, unc_meta, unc_spec]:
        if not df.empty:
            df.reindex(columns=sorted(df.columns), copy=False)

    return ref_meta, ref_spec, unc_meta, unc_spec

def create_radcalnet_color_dict(wavelengths):
    """Generates a dictionary mapping RadCalNet integer wavelengths to accurate

    visible spectrum hex colors, or custom palettes starting at Burgundy for IR.
    """
    color_dict = {}
    unique_wls = sorted(list(set(int(wl) for wl in wavelengths)))

    for wl in unique_wls:
        # --- 1. Ultraviolet Range (< 380 nm) ---
        if wl < 380:
            color_dict[wl] = "#3D0066"  # Deep Purple

        # --- 2. Visible Spectrum Range (380 - 750 nm) ---
        elif 380 <= wl <= 750:
            if 380 <= wl < 440:
                R, G, B = (440 - wl) / (440 - 380), 0.0, 1.0
            elif 440 <= wl < 490:
                R, G, B = 0.0, (wl - 440) / (490 - 440), 1.0
            elif 490 <= wl < 510:
                R, G, B = 0.0, 1.0, (510 - wl) / (510 - 490)
            elif 510 <= wl < 580:
                R, G, B = (wl - 510) / (580 - 510), 1.0, 0.0
            elif 580 <= wl < 645:
                R, G, B = 1.0, (645 - wl) / (645 - 580), 0.0
            else:
                R, G, B = 1.0, 0.0, 0.0

            factor = (
                0.3 + 0.7 * (wl - 380) / (420 - 380)
                if 380 <= wl < 420
                else (
                    0.3 + 0.7 * (750 - wl) / (750 - 700)
                    if 700 <= wl <= 750
                    else 1.0
                )
            )
            color_dict[wl] = "#{:02x}{:02x}{:02x}".format(
                int(R * factor * 255),
                int(G * factor * 255),
                int(B * factor * 255),
            )

        # --- 3. Infrared / SWIR Range (751 - 2500 nm) ---
        else:
            # Isolate the IR specific wavelengths in the query
            ir_wls = [w for w in unique_wls if w > 750]
            if len(ir_wls) > 1:
                idx = ir_wls.index(wl)
                normalized_idx = idx / (len(ir_wls) - 1)
            else:
                normalized_idx = 0.0

            # Define RGB endpoints for interpolation
            # Starts at a rich Burgundy and transitions to a warm Rust-Bronze
            burgundy = np.array([128, 0, 32])  # Deep Burgundy
            rust_bronze = np.array([210, 105, 30])  # Warm Rust / Chocolate Bronze

            # Linear color interpolation based on position in IR range
            rgb_interp = burgundy + (rust_bronze - burgundy) * normalized_idx
            color_dict[wl] = "#{:02x}{:02x}{:02x}".format(
                int(rgb_interp[0]), int(rgb_interp[1]), int(rgb_interp[2])
            )

    return color_dict


import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_boa_vs_toa_with_colors(
    input_spectra, output_spectra, wavelengths, site_name=None
):
    """Plots BOA vs TOA reflectance using a context-aware color dictionary.

    Automatically pads missing observation days with explicit NaNs to prevent
    lines from connecting across multi-day or multi-year data gaps.
    """
    # 1. Clean row duplicates by averaging
    clean_in = input_spectra.groupby(level=0).mean()
    clean_out = output_spectra.groupby(level=0).mean()

    # 2. Strict datetime conversion of column headers BEFORE parsing
    clean_in.columns = pd.to_datetime(clean_in.columns)
    clean_out.columns = pd.to_datetime(clean_out.columns)

    # 3. Find global min and max dates across both stages to anchor the grid bounds
    all_times = pd.to_datetime(
        list(clean_in.columns) + list(clean_out.columns)
    )
    if len(all_times) < 2:
        print("Not enough timeline points to map a continuous grid.")
        return

    min_date = all_times.min().floor("D")
    max_date = all_times.max().ceil("D")

    # 4. TIMELINE PADDING: Build a continuous 30-minute frequency time grid
    continuous_grid = pd.date_range(start=min_date, end=max_date, freq="30min")

    # Reindex onto the continuous grid to insert empty rows/NaN slots for missing days
    clean_in = clean_in.reindex(columns=continuous_grid)
    clean_out = clean_out.reindex(columns=continuous_grid)

    # 5. Generate the global visual color mapping dictionary
    master_colors = create_radcalnet_color_dict(clean_in.index)

    fig, ax = plt.subplots(figsize=(12, 6))

    for wl in wavelengths:
        # Cast key to match index datatype
        wl_key = wl if wl in clean_in.index else str(wl)

        if wl_key not in clean_in.index or wl_key not in clean_out.index:
            continue

        # Force rows to numeric arrays while keeping newly padded NaNs intact
        boa_vals = pd.to_numeric(clean_in.loc[wl_key].values, errors="coerce")
        toa_vals = pd.to_numeric(clean_out.loc[wl_key].values, errors="coerce")

        # Skip drawing if a channel contains absolutely no data points
        if np.isnan(boa_vals).all() or np.isnan(toa_vals).all():
            continue

        assigned_color = master_colors.get(wl_key, "#808080")

        # 6. Plot Ground (BOA) as a solid line
        # Passing continuous_grid means lines break whenever an empty gap hits
        ax.plot(
            continuous_grid,
            boa_vals,
            linestyle="-",
            marker="o",
            markersize=3,  # Adjusted smaller marker profile for clean timelines
            color=assigned_color,
            label=f"{wl}nm (BOA)",
        )

        # 7. Plot TOA as a dashed line
        ax.plot(
            continuous_grid,
            toa_vals,
            linestyle="--",
            marker="x",
            markersize=3,  # Adjusted smaller marker profile
            color=assigned_color,
            label=f"{wl}nm (TOA)",
        )

    # 8. Title and Formatting Engine
    if site_name:
        resolved_code = SITE_NAME_TO_CODE.get(site_name, site_name)
        resolved_long = SITE_CODE_TO_NAME.get(resolved_code, site_name)
        chart_title = (
            f"RadCalNet BOA and TOA reflectance timeline: {resolved_long} ({resolved_code})"
        )
    else:
        chart_title = "RadCalNet BOA and TOA reflectance timeline"

    ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("Date and Time (UTC)", fontsize=12)
    ax.set_ylabel("Reflectance", fontsize=12)
    ax.set_ylim(bottom=0)

    ax.xaxis.set_major_formatter(
        plt.matplotlib.dates.DateFormatter("%Y-%m-%d %H:%M")
    )
    fig.autofmt_xdate(rotation=35)

    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(bbox_to_anchor=(1.04, 1), loc="upper left", frameon=True)

    plt.tight_layout()
    plt.show()

import matplotlib.pyplot as plt


def plot_spectral_signature_curve(
    input_spectra, output_spectra, timestamp_str, site_name=None, x_lim=[390,2310], y_lim=[0,0.5]
):
    """Plots the full spectrum (400-2500nm) for one specific date and time.

    Leaves lines disconnected across NoData gaps and applies site name mapping.
    """
    if timestamp_str not in input_spectra.columns:
        print(f"Timestamp {timestamp_str} not found.")
        return

    plt.figure(figsize=(10, 5))

    # Generate the global visual color mapping for every wavelength
    colors = create_radcalnet_color_dict(input_spectra.index)

    # Sort index so wavelengths flow sequentially on X-axis
    sorted_index = sorted(input_spectra.index)

    boa_curve = [input_spectra.loc[wl, timestamp_str] for wl in sorted_index]
    toa_curve = [output_spectra.loc[wl, timestamp_str] for wl in sorted_index]

    # Plot solid line for BOA, dashed line for TOA
    plt.plot(sorted_index, boa_curve, "-", color="black", alpha=0.3)
    plt.plot(sorted_index, toa_curve, "--", color="gray", alpha=0.3)

    # Scatter points with their real descriptive colors
    for wl in sorted_index:
        c = colors.get(wl, "#808080")
        plt.scatter(
            wl,
            input_spectra.loc[wl, timestamp_str],
            color=c,
            marker="o",
            s=20,
        )
        plt.scatter(
            wl,
            output_spectra.loc[wl, timestamp_str],
            color=c,
            marker="x",
            s=20,
        )

    # Empty proxies for clean legend handling
    plt.scatter([], [], color="black", marker="o", label="BOA")
    plt.scatter(
        [], [], color="black", marker="x", label="TOA"
    )

    # Generate dynamic chart descriptive titles
    if site_name:
        resolved_code = SITE_NAME_TO_CODE.get(site_name, site_name)
        resolved_long = SITE_CODE_TO_NAME.get(resolved_code, site_name)
        chart_title = f"RadCalNet spectral signature profile: {resolved_long} ({resolved_code}) \n[{timestamp_str}]"
    else:
        chart_title = (
            f"RadCalNet spectral signature profile \n[{timestamp_str}]"
        )

    # --- NEW: APPLY CUSTOM AXIS LIMITS IF PROVIDED ---
    if x_lim is not None:
        plt.xlim(x_lim)  # Expects tuple like (min, max), e.g., (400, 1000)
    if y_lim is not None:
        plt.ylim(y_lim)  # Expects tuple like (min, max), e.g., (0.0, 0.5)

    plt.title(chart_title, fontweight="bold", pad=15)
    plt.xlabel("Wavelength (nm)", fontsize=11)
    plt.ylabel("Reflectance", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.show()


def plot_atmospheric_attenuation(
    input_spectra, output_spectra, wavelengths, site_name=None
):
    """Plots the absolute difference (TOA - BOA) over time to track atmospheric attenuation.

    Guarantees a clean date axis and forces lines to disconnect across unobserved days.
    """
    # 1. Clean row duplicates by averaging
    clean_in = input_spectra.groupby(level=0).mean()
    clean_out = output_spectra.groupby(level=0).mean()

    # 2. Strict datetime conversion of column headers BEFORE formatting or matching
    clean_in.columns = pd.to_datetime(clean_in.columns)
    clean_out.columns = pd.to_datetime(clean_out.columns)

    # 3. Find mutual timestamps present in both matrices
    mutual_times = clean_in.columns.intersection(clean_out.columns)
    if len(mutual_times) == 0:
        print("Error: No matching timestamps found between Input and Output stages.")
        return

    # Slice and sort chronologically
    mutual_times = sorted(mutual_times)
    clean_in = clean_in[mutual_times]
    clean_out = clean_out[mutual_times]

    # 4. TIMELINE PADDING: Inject explicit NaNs for missing days to break lines
    # Generate an uninterrupted daily grid from earliest to latest valid file date
    min_date = pd.to_datetime(mutual_times).min().floor('D')
    max_date = pd.to_datetime(mutual_times).max().ceil('D')
    
    # We build a 30-minute frequency grid to align with RadCalNet tracking steps
    continuous_grid = pd.date_range(start=min_date, end=max_date, freq="30min")

    # Reindex onto the continuous grid to pad missing days with explicit NaNs
    clean_in = clean_in.reindex(columns=continuous_grid)
    clean_out = clean_out.reindex(columns=continuous_grid)

    # 5. Generate the global visual color mapping dictionary
    colors = create_radcalnet_color_dict(clean_in.index)

    fig, ax = plt.subplots(figsize=(12, 5))

    for wl in wavelengths:
        wl_key = wl if wl in clean_in.index else str(wl)

        if wl_key not in clean_in.index or wl_key not in clean_out.index:
            continue

        # Force rows to numeric arrays while keeping newly padded NaNs intact
        boa_vals = pd.to_numeric(clean_in.loc[wl_key].values, errors="coerce")
        toa_vals = pd.to_numeric(clean_out.loc[wl_key].values, errors="coerce")

        if np.isnan(boa_vals).all() or np.isnan(toa_vals).all():
            continue

        # Calculate Delta (TOA - BOA)
        delta = toa_vals - boa_vals

        assigned_color = colors.get(wl_key, "#808080")

        # 6. Plot the tracking curves
        # Passing the continuous_grid with embedded NaNs forces lines to snap dead across gaps
        ax.plot(
            continuous_grid,
            delta,
            linestyle="-",
            marker="s",
            markersize=3,
            #markevery=2,  # Renders a marker on every other valid data point
            color=assigned_color,
            label=f"{wl}nm ($\Delta$ TOA-BOA)",
        )

    # 7. Generate dynamic chart descriptive titles
    if site_name:
        resolved_code = SITE_NAME_TO_CODE.get(site_name, site_name)
        resolved_long = SITE_CODE_TO_NAME.get(resolved_code, site_name)
        chart_title = f"Atmospheric attenuation timeline: {resolved_long} ({resolved_code})\n($\Delta$ Reflectance)"
    else:
        chart_title = "Atmospheric attenuation timeline ($\Delta$ Reflectance)"

    ax.set_title(chart_title, fontweight="bold", pad=15)
    ax.set_xlabel("Date and Time (UTC)", fontsize=11)
    ax.set_ylabel("Reflectance $\Delta$ (TOA - BOA)", fontsize=11)
    ax.axhline(0, color="black", linestyle="--", alpha=0.5)

    # Format the time axis labels securely
    ax.xaxis.set_major_formatter(
        plt.matplotlib.dates.DateFormatter("%Y-%m-%d %H:%M")
    )
    fig.autofmt_xdate(rotation=35)

    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(bbox_to_anchor=(1.04, 1), loc="upper left", frameon=True)
    plt.tight_layout()
    plt.show()

def plot_diurnal_overlay(spectra_df, wavelength, site_name=None):
    """
    Overlays the time-of-day trends for a single wavelength, grouping by calendar date.
    """
    timestamps = pd.to_datetime(spectra_df.columns)
    unique_dates = sorted(list(set(timestamps.date)))
    
    plt.figure(figsize=(10, 5))
    
    # Map colors uniquely to dates using a standard matplotlib cmap
    colormap = cm.get_cmap('plasma', len(unique_dates))
    
    for idx, d in enumerate(unique_dates):
        # Slice only columns belonging to this specific date
        mask = timestamps.date == d
        date_times = timestamps[mask]
        
        # Sort values cleanly by hour/minute
        time_strings = [dt.strftime('%H:%M') for dt in date_times]
        values = pd.to_numeric(spectra_df.loc[wavelength, mask].values)
        
        # Create a sorted pairing
        sorted_pairs = sorted(zip(time_strings, values))
        x_hours = [p[0] for p in sorted_pairs]
        y_vals = [p[1] for p in sorted_pairs]
        
        plt.plot(x_hours, y_vals, marker='o', label=str(d), color=colormap(idx))

        if site_name:
            resolved_code = SITE_NAME_TO_CODE.get(site_name, site_name)
            resolved_long = SITE_CODE_TO_NAME.get(resolved_code, site_name)
            chart_title = f"Diurnal solar curve at {wavelength}nm: {resolved_long} ({resolved_code})"
        else:
            chart_title = f"Diurnal solar curve at {wavelength}nm"
        
    plt.title(chart_title, fontweight='bold')
    plt.xlabel("Time of Day (UTC Hour)")
    plt.ylabel("Reflectance")
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.legend(title="Observation Date")
    plt.show()

def load_site_dataset(base_data_dir, site_code, stage="input"):
    """Recursively walks through all year subdirectories for a specific site

    and transforms the data blocks into a standardized long-form dataframe.
    """
    site_root_dir = os.path.join(base_data_dir, site_code)

    if not os.path.exists(site_root_dir):
        print(f"Warning: Directory path does not exist: {site_root_dir}")
        return pd.DataFrame()

    stage_ext = stage.lower().replace(".", "")
    all_file_meta = []
    all_file_spec = []

    # Recursively search through all subfolders
    for root, dirs, files in os.walk(site_root_dir):
        for file in files:
            if file.lower().endswith(f".{stage_ext}"):
                file_path = os.path.join(root, file)

                # Parse file blocks using your function
                meta_blocks, spec_blocks = parse_multi_dataset_file(file_path)

                if len(meta_blocks) >= 1:
                    all_file_meta.extend(meta_blocks)
                    all_file_spec.extend(spec_blocks)

    if not all_file_spec:
        print(
            f"Warning: No valid '.{stage_ext}' files compiled for site {site_code}"
        )
        return pd.DataFrame()

    # Concatenate the flat list of DataFrames side-by-side
    spec_df = pd.concat(all_file_spec, axis=1, sort=False)

    # FIX: Call .round() directly on the series object, not on 'pd'
    spec_df.index = spec_df.index.to_series().round().astype(int)
    spec_df.columns = pd.to_datetime(spec_df.columns)

    # Reshape wide matrix to long-form data
    long_df = spec_df.reset_index().melt(
        id_vars="Wavelength", var_name="DateTime", value_name="Reflectance"
    )

    # Apply processing tags
    long_df["Site"] = site_code
    long_df["Stage"] = stage.upper()

    # Drop RadCalNet Fill/NoData flags (9997, 9998, 9999) from calculations
    long_df = long_df[long_df["Reflectance"] < 2.0]

    return long_df

def plot_multi_site_timelines_with_colors(master_df, wavelengths):
    """
    Cycles through your long master dataframe by site code, maps the short
    code to its descriptive name, and routes data frames into the core function.
    """
    for site_code in master_df["Site"].unique():
        # Retrieve the long human-readable name or fallback to the code string
        descriptive_name = SITE_CODE_TO_NAME.get(site_code, site_code)
        
        # Isolate the dataset for the current station
        site_df = master_df[master_df["Site"] == site_code]

        in_data = site_df[site_df["Stage"] == "INPUT"]
        out_data = site_df[site_df["Stage"] == "OUTPUT"]

        if in_data.empty or out_data.empty:
            continue

        in_wide = in_data.pivot_table(index="Wavelength", columns="DateTime", values="Reflectance", aggfunc="first")
        out_wide = out_data.pivot_table(index="Wavelength", columns="DateTime", values="Reflectance", aggfunc="first")

        # Call your updated core routine passing the resolved site text name
        plot_boa_vs_toa_with_colors(
            input_spectra=in_wide,
            output_spectra=out_wide,
            wavelengths=wavelengths,
            site_name=descriptive_name
        )

def plot_multi_site_signatures(master_df, target_date_str):
    """Finds the closest operational data overpass matching your target date

    for each individual site, and prints its continuous wavelength signature.
    """
    target_dt = pd.to_datetime(target_date_str)

    for site_code in master_df["Site"].unique():
        descriptive_name = SITE_CODE_TO_NAME.get(site_code, site_code)
        site_df = master_df[master_df["Site"] == site_code]

        # Isolate site specific timestamps
        available_times = pd.to_datetime(site_df["DateTime"].unique())

        if len(available_times) == 0:
            continue

        # Find the absolute closest observation time available at this site
        closest_time = available_times[np.argmin(np.abs(available_times - target_dt))]
        closest_time_str = closest_time.strftime("%Y-%m-%d %H:%M")

        print(f"\nSite {site_code}: Target date is {target_date_str}.")
        print(f"-> Closest available record found at: {closest_time_str}")

        # Build wide tables
        in_wide = (
            site_df[site_df["Stage"] == "INPUT"]
            .pivot_table(
                index="Wavelength",
                columns="DateTime",
                values="Reflectance",
                aggfunc="first",
            )
        )
        out_wide = (
            site_df[site_df["Stage"] == "OUTPUT"]
            .pivot_table(
                index="Wavelength",
                columns="DateTime",
                values="Reflectance",
                aggfunc="first",
            )
        )

        # Call your original curve profile tool
        plot_spectral_signature_curve(
            input_spectra=in_wide,
            output_spectra=out_wide,
            timestamp_str=closest_time,  # Pass the datetime object or exact matching string
            site_name=descriptive_name
        )



def plot_multi_site_attenuation(master_df, wavelengths):
    """Generates pure atmospheric distortion delta graphs per station."""
    for site_code in master_df["Site"].unique():
        descriptive_name = SITE_CODE_TO_NAME.get(site_code, site_code)
        site_df = master_df[master_df["Site"] == site_code]

        in_wide = (
            site_df[site_df["Stage"] == "INPUT"]
            .pivot_table(
                index="Wavelength",
                columns="DateTime",
                values="Reflectance",
                aggfunc="first",
            )
        )
        out_wide = (
            site_df[site_df["Stage"] == "OUTPUT"]
            .pivot_table(
                index="Wavelength",
                columns="DateTime",
                values="Reflectance",
                aggfunc="first",
            )
        )

        plot_atmospheric_attenuation(
            input_spectra=in_wide,
            output_spectra=out_wide,
            wavelengths=wavelengths,
            site_name=descriptive_name
        )


def plot_multi_site_diurnal(master_df, target_wavelength):
    """Overlays diurnal solar cycle profiles sorted by date for each site location."""
    for site_code in master_df["Site"].unique():
        descriptive_name = SITE_CODE_TO_NAME.get(site_code, site_code)
        site_df = master_df[master_df["Site"] == site_code]

        # Extract stages independently
        in_wide = (
            site_df[site_df["Stage"] == "INPUT"]
            .pivot_table(
                index="Wavelength",
                columns="DateTime",
                values="Reflectance",
                aggfunc="first",
            )
        )

        print(f"\n--- Diurnal Ground Trend (BOA) for Station: {site_code} ---")
        plot_diurnal_overlay(spectra_df=in_wide, wavelength=target_wavelength, site_name=descriptive_name)


# Load required libraries
library(sf)
library(dplyr)
library(ggplot2)
library(patchwork)
library(lubridate)
library(scales)
# library(rnaturalearth)
# library(rnaturalearthdata)
library(viridis)
library(ggspatial)

# Platform-specific column mapping vectors
library(viridisLite)

library(viridisLite)

# Function to create sensor color mapping
create_sensor_colors <- function(sensors = NULL, palette = "turbo") {
  
  # Default comprehensive sensor list
  if (is.null(sensors)) {
    sensors <- c(
      # Maxar WorldView
      'WV01', 'WV02', 'WV03', 'WV04',
      
      # Maxar Legacy
      'QB02', 'GE01', 'IKONOS',
      
      # Maxar Legion
      'LG01', 'LG02', 'LG03', 'LG04', 'LG05', 'LG06',
      
      # Airbus SPOT
      'SPOT6', 'SPOT7',
      
      # Airbus Pleiades
      'PHR1A', 'PHR1B',
      
      # Sentinel
      'MSI',
      
      # Planet
      'PS0', 'PS1', 'PS2', 'PS2.SD', 'PSB.SD', 'RE'
    )
  }
  
  # Generate colors
  n_sensors <- length(sensors)
  colors <- viridis(n_sensors, option = palette)
  
  # Create named vector
  sensor_colors <- setNames(colors, sensors)
  
  return(sensor_colors)
}

# sensor_full_names <- c(
#   'MSI' = 'Sentinel-2',
#   'PS0' = 'PlanetScope 0 (Dove Classic)',
#   'PS1' = 'PlanetScope 1 (Dove-R)',
#   'PS2' = 'PlanetScope 2 (Dove)',
#   'PS2.SD' = 'PlanetScope 2 SuperDove',
#   'PSB.SD' = 'PlanetScope SuperDove'
# )
sensor_full_names <- c(
  'MSI' = 'Sentinel-2',
  'PS0' = 'Dove Classic (PS0)',
  'PS1' = 'Dove-R (PS1)',
  'PS2' = 'Dove (PS2)',
  'PS2.SD' = 'SuperDove (PS2.SD)',
  'PSB.SD' = 'SuperDove (PSB.SD)'
)

sensor_colors <- create_sensor_colors()

# CSDA needs more of these
standardized_cols = c('id','collection')

# Maps from: standard_name -> platform_specific_column

planet_col_mapping <- c(
    'datetime' = 'datetime',
    'affiliation' = 'collection',
    'sensor/generation' = 'eo.instrument',  
    'constellation' = 'pl.providor',
    'sat_id' = 'pl.satellite_id',
    
    'el' = 'eo.off_nadir',           # Note: Planet doesn't provide view elevation directly
    'az' = 'eo.azimuth',              # View azimuth
    'sunel' = 'eo.sun_elevation',    # Sun elevation
    'sunaz' = 'eo.sun_azimuth',      # Sun azimuth
    'offnadir' = 'eo.off_nadir',     # Off-nadir angle
    'gsd' = 'eo.gsd'                 # Ground sample distance
)
# # For future platforms:
sentinel2_col_mapping <- c(
  'el' = 'view_elevation',          # Adjust based on actual S2 STAC schema
  'az' = 'view_azimuth',
  'sunel' = 'sun_elevation',
  'sunaz' = 'sun_azimuth',
  'offnadir' = 'off_nadir',
  'gsd' = 'gsd'
)
maxar_legion_col_mapping <- c(
    'datetime' = 'end_datetime',
    'affiliation' = 'collection',
    'sensor/generation' = 'instrument',  
    'constellation' = 'collection',
    'sat_id' = 'platform',
    
    'el' = 'maxar_legion.mean_sat_elevation',          # Adjust based on actual Maxar STAC schema
    'az' = 'view.azimuth',
    'sunel' = 'view.sun_elevation',
    'sunaz' = 'view.sun_azimuth',
    'offnadir' = 'view.off_nadir',
    'gsd' = 'gsd'
)
satellogic_col_mapping <- c(
    'datetime' = 'datetime',
    'affiliation' = 'collection',
    'sensor/generation' = 'platform',  
    'constellation' = 'constellation',
    'sat_id' = 'satl.sat_id',
    
    'el' = 'view.off_nadir',          # Adjust based on actual Maxar STAC schema
    'az' = 'view.azimuth',
    'sunel' = 'view.sun_elevation',
    'sunaz' = 'view.sun_azimuth',
    'offnadir' = 'view.off_nadir',
    'gsd' = 'gsd'
)

# Store all mappings in a list for easy access
platform_mappings <- list(
  'planet' =       planet_col_mapping,
  'sentinel2' =    sentinel2_col_mapping,
  'maxar-legion' = maxar_legion_col_mapping,
  'satellogic' =   satellogic_col_mapping
)

standardize_stac_columns <- function(gdf, platform = 'planet') {
  
  # Get the appropriate mapping
  col_mapping <- platform_mappings[[platform]]
  
  if (is.null(col_mapping)) {
    stop(paste("Platform", platform, "not recognized. Available platforms:", 
               paste(names(platform_mappings), collapse = ", ")))
  }
  
  # Create a copy with standardized column names
  gdf_std <- gdf
  
  # Rename columns according to mapping
  for (std_name in names(col_mapping)) {
    platform_col <- col_mapping[std_name]
    if (platform_col %in% names(gdf_std)) {
      gdf_std[[std_name]] <- gdf_std[[platform_col]]
    } else {
      warning(paste("Column", platform_col, "not found in dataframe for", std_name))
      gdf_std[[std_name]] <- NA
    }
  }

  if(PLATFORM == 'planet' | PLATFORM == 'satellogic'){
      # Calculate view elevation from off-nadir - which is info provided to the 'el' col initially 
      gdf_std$el <- 90 - gdf_std$el
  }
    
  # Return only standard set of colnames
  gdf_std = gdf_std %>% select(all_of(c(standardized_cols, names(col_mapping))))
    
  return(gdf_std)
}

add_temporal_fields <- function(gdf, datetime_col = 'datetime') {
  
  # Check if datetime column exists
  if (!datetime_col %in% names(gdf)) {
    stop(paste("Column", datetime_col, "not found in dataframe"))
  }
  
  # Convert to POSIXct if not already
  if (!inherits(gdf[[datetime_col]], c("POSIXct", "POSIXlt", "Date"))) {
    gdf[[datetime_col]] <- as.POSIXct(gdf[[datetime_col]])
  }
  
  # Extract temporal fields
  gdf$date <- as.Date(gdf[[datetime_col]])
  gdf$year <- as.integer(format(gdf[[datetime_col]], "%Y"))
  gdf$month <- as.integer(format(gdf[[datetime_col]], "%m"))
  gdf$doy <- as.integer(format(gdf[[datetime_col]], "%j"))
  
  return(gdf)
}

# Dashboard Functions =============================================================================
# PLOT 1: OVERVIEW MAP (Orthographic-style)
# =============================================================================
create_overview_map <- function(footprints, title = "Footprints of spaceborne VHR images", 
                               zoom = FALSE, color_limits = c(0, 100), zoom_circle_scale = 1.0) {
  
  # Get world map
  #world <- ne_countries(scale = "medium", returnclass = "sf")
  require(maps)
  world = map_data("world")
  # Convert to sf object
  world <- st_as_sf(world, 
                     coords = c("long", "lat"), 
                     crs = 4326)
  
  # Calculate center
  center_lon <- mean(st_coordinates(st_transform(footprints, 4326) %>% st_centroid())[,1])
  center_lat <- mean(st_coordinates(st_transform(footprints, 4326) %>% st_centroid())[,2])
  
  # Transform to orthographic
  ortho_crs <- sprintf("+proj=ortho +lat_0=%f +lon_0=%f", center_lat, center_lon)
  
  world_ortho <- st_transform(world, ortho_crs)
  footprints_ortho <- st_transform(footprints, ortho_crs)
  
  # Function to safely transform and clip lines
  safe_transform <- function(linestring_coords, crs_from, crs_to) {
    tryCatch({
      line <- st_linestring(linestring_coords)
      line_sf <- st_sfc(line, crs = crs_from)
      transformed <- st_transform(line_sf, crs_to)
      if (st_is_valid(transformed)) return(transformed)
      else return(NULL)
    }, error = function(e) NULL)
  }
  
  # Create graticules - latitude lines
  lat_lines_list <- list()
  lats <- seq(-80, 80, by = 30)
  for (lat in lats) {
    for (lon_start in seq(-180, 150, by = 30)) {
      lon_end <- lon_start + 30
      lon_seq <- seq(lon_start, lon_end, by = 0.5)
      coords <- cbind(lon_seq, rep(lat, length(lon_seq)))
      result <- safe_transform(coords, 4326, ortho_crs)
      if (!is.null(result)) {
        lat_lines_list[[length(lat_lines_list) + 1]] <- result
      }
    }
  }
  lat_lines_sf <- do.call(c, lat_lines_list)
  
  # Create graticules - longitude lines
  lon_lines_list <- list()
  lons <- seq(-180, 150, by = 30)
  for (lon in lons) {
    for (lat_start in seq(-90, 60, by = 30)) {
      lat_end <- lat_start + 30
      lat_seq <- seq(lat_start, lat_end, by = 0.5)
      coords <- cbind(rep(lon, length(lat_seq)), lat_seq)
      result <- safe_transform(coords, 4326, ortho_crs)
      if (!is.null(result)) {
        lon_lines_list[[length(lon_lines_list) + 1]] <- result
      }
    }
  }
  lon_lines_sf <- do.call(c, lon_lines_list)
  
  # Create Arctic Circle (66.5°N)
  arctic_lines_list <- list()
  for (lon_start in seq(-180, 150, by = 30)) {
    lon_end <- lon_start + 30
    lon_seq <- seq(lon_start, lon_end, by = 0.5)
    coords <- cbind(lon_seq, rep(66.5, length(lon_seq)))
    result <- safe_transform(coords, 4326, ortho_crs)
    if (!is.null(result)) {
      arctic_lines_list[[length(arctic_lines_list) + 1]] <- result
    }
  }
  arctic_circle_sf <- do.call(c, arctic_lines_list)
  
  # Create base plot function
  create_base_plot <- function(zoomed = FALSE, show_legend = TRUE, show_zoom_circle = FALSE, zoom_center = NULL, zoom_radius = NULL) {
    p <- ggplot() +
      # Graticules
      geom_sf(data = lat_lines_sf, color = "gray60", size = 0.1, 
              linetype = "solid", alpha = 0.1) +
      geom_sf(data = lon_lines_sf, color = "gray60", size = 0.1, 
              linetype = "solid", alpha = 0.1) +
      # Ocean (white background)
      geom_sf(data = world_ortho, fill = "lightgray", color = "darkgray", 
              size = 0.2) +
      # Arctic Circle
      geom_sf(data = arctic_circle_sf, color = "black", size = 0.5,
              linetype = "dotted")
    
    if (zoomed) {
      # Colored footprints for zoomed map
      p <- p + 
        geom_sf(data = footprints_ortho, aes(fill = ang_div), 
                size = 0, alpha = 0.6, color = NA) +
        scale_fill_viridis_c(
          option = "turbo",
          limits = color_limits,
          direction = -1,
          name = "Sensor position\nangular\ndivergence (°)",
          guide = if(show_legend) "colorbar" else "none"
        ) #+
        # # Add scale bar
        # annotation_scale(
        #   location = "br",  # bottom right
        #   width_hint = 0.25,
        #   style = "ticks",
        #   line_width = 1,
        #   height = unit(0.15, "cm"),
        #   text_cex = 0.8,
        #   pad_x = unit(0.5, "cm"),
        #   pad_y = unit(0.5, "cm")
        # ) +
        # # Add north arrow
        # annotation_north_arrow(
        #   location = "tl",  # top left
        #   which_north = "true",
        #   pad_x = unit(0.3, "cm"),
        #   pad_y = unit(0.3, "cm"),
        #   style = north_arrow_minimal(
        #     line_width = 1,
        #     text_size = 3
        #   )
        # )
    } else {
      # Black footprints for full extent
      p <- p + 
        geom_sf(data = footprints_ortho, size = 0, alpha = 0.2, color = NA, fill = "black")
      
      # Add zoom circle if requested
      if (show_zoom_circle && !is.null(zoom_center) && !is.null(zoom_radius)) {
        # Create circle geometry
        circle <- st_buffer(st_point(c(zoom_center$x, zoom_center$y)), dist = zoom_radius)
        circle_sf <- st_sfc(circle, crs = ortho_crs)
        
        p <- p + 
          geom_sf(data = circle_sf, fill = NA, color = "red", size = 1, linetype = "solid")
      }
    }
    
    return(p)
  }
  
  # Create full extent plot
  p_full <- create_base_plot(zoomed = FALSE, show_legend = FALSE) +
    annotate("text", x = Inf, y = Inf, 
             label = sprintf("n = %s", format(nrow(footprints), big.mark = ",")),
             hjust = 1.1, vjust = 1.5, size = 4,
             fontface = "bold") +
    labs(title = title) +
    theme_void() +
    theme(
      plot.title = element_text(face = "bold", size = 12, hjust = 0.5),
      plot.background = element_rect(fill = "white", color = NA),
      panel.background = element_rect(fill = "white", color = NA)
    )
  
  # If not zooming, return full extent plot
  if (!zoom) {
    return(p_full)
  }
  
  # Calculate zoom extent
  bbox <- st_bbox(footprints_ortho)
  buffer <- max(bbox$xmax - bbox$xmin, bbox$ymax - bbox$ymin) * 0.1
  
  # Calculate zoom center and radius for circle
  zoom_center <- list(
    x = (bbox$xmin + bbox$xmax) / 2,
    y = (bbox$ymin + bbox$ymax) / 2
  )
  zoom_radius <- max(
    bbox$xmax - bbox$xmin + 2 * buffer,
    bbox$ymax - bbox$ymin + 2 * buffer
  ) / 2 * zoom_circle_scale
  
  # Create zoomed plot
  p_zoom <- create_base_plot(zoomed = TRUE, show_legend = TRUE) +
    coord_sf(
      xlim = c(bbox$xmin - buffer, bbox$xmax + buffer),
      ylim = c(bbox$ymin - buffer, bbox$ymax + buffer),
      expand = FALSE
    ) +
    annotate("text", x = Inf, y = Inf, 
             label = sprintf("n = %s", format(nrow(footprints), big.mark = ",")),
             hjust = 1.1, vjust = 1.5, size = 4,
             fontface = "bold") +
    labs(title = title) +
    theme_void() +
    theme(
      plot.title = element_text(face = "bold", size = 12, hjust = 0.5),
      plot.background = element_rect(fill = "white", color = NA),
      panel.background = element_rect(fill = "white", color = NA),
      legend.position = "right"
    )
  
  # Create inset with zoom circle
  p_inset <- create_base_plot(zoomed = FALSE, show_legend = FALSE, 
                              show_zoom_circle = TRUE, 
                              zoom_center = zoom_center, 
                              zoom_radius = zoom_radius) +
    annotate("text", x = Inf, y = Inf, 
             label = sprintf("n = %s", format(nrow(footprints), big.mark = ",")),
             hjust = 1.1, vjust = 1.5, size = 3,
             fontface = "bold") +
    labs(title = NULL) +
    theme_void() +
    theme(
      axis.text = element_blank(),
      plot.background = element_rect(fill = "white", color = "black", size = 0.5)
    )
  
  # Combine with inset
  p_final <- p_zoom +
    inset_element(p_inset, left = 0.0, bottom = 0.0, right = 0.35, top = 0.35)
  
  return(p_final)
}

# =============================================================================
# PLOT 2: POLAR PLOT (Acquisition Geometry)
# =============================================================================
create_polar_plot <- function(footprints, title = "Skyplot of acquisition geometry", 
                              color_palette = 'turbo', color_limits = c(0, 100),
                              facet_by = NULL) {
  
  library(dplyr)
  library(ggplot2)
  library(sf)
  
  # Drop geometry and prepare data
  plot_data <- footprints %>%
    st_drop_geometry() %>%
    filter(!is.na(az), !is.na(el), !is.na(ang_div))
  
  if (!is.null(facet_by)) {
    plot_data <- plot_data %>%
      filter(!is.na(.data[[facet_by]]))
  }
  
  if (nrow(plot_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  # Prepare sensor data
  plot_data <- plot_data %>%
    mutate(
      theta = az * pi / 180,
      r = 90 - el
    )
  
  # Prepare sun data
  sun_data <- plot_data %>%
    mutate(
      theta_sun = sunaz * pi / 180,
      r_sun = 90 - sunel
    ) %>%
    select(theta_sun, r_sun, any_of(facet_by)) %>%
    distinct()
  
  # Sun center labels
  if (!is.null(facet_by)) {
    sun_center <- sun_data %>%
      group_by(.data[[facet_by]]) %>%
      summarize(
        theta_sun = mean(theta_sun, na.rm = TRUE),
        r_sun = quantile(r_sun, probs = 0.98, na.rm = TRUE),
        .groups = 'drop'
      )
  } else {
    sun_center <- sun_data %>%
      summarize(
        theta_sun = mean(theta_sun, na.rm = TRUE),
        r_sun = quantile(r_sun, probs = 0.98, na.rm = TRUE)
      )
  }
  
  # Zenith labels
  if (!is.null(facet_by)) {
    facet_levels <- unique(plot_data[[facet_by]])
    zenith_labels <- expand.grid(
      r = c(30, 60, 90),
      facet_col = facet_levels,
      stringsAsFactors = FALSE
    ) %>%
      mutate(
        theta = pi/4,
        label = paste0(r, "°")
      )
    names(zenith_labels)[names(zenith_labels) == "facet_col"] <- facet_by
  } else {
    zenith_labels <- data.frame(
      theta = pi/4,
      r = c(30, 60, 90),
      label = c("30°", "60°", "90°")
    )
  }
  
  # Build plot
  p <- ggplot(plot_data, aes(x = theta, y = r, color = ang_div)) +
    geom_point(size = 1.25, alpha = 0.75) +
    geom_point(data = sun_data, aes(x = theta_sun, y = r_sun),
               inherit.aes = FALSE,
               size = 1, shape = 21, fill = "orange", color = "black",
               stroke = 0.25, alpha = 0.1) +
    geom_point(aes(x = 0, y = 0), inherit.aes = FALSE,
               shape = 3, size = 2, color = "red", stroke = 1) +
    geom_text(data = zenith_labels, aes(x = theta, y = r, label = label),
              inherit.aes = FALSE,
              size = 3, color = "gray30", fontface = "bold") +
    geom_label(data = sun_center, aes(x = theta_sun, y = r_sun, label = "Sun pos."),
               inherit.aes = FALSE,
               size = 3.0, fontface = "italic", color = "orange", vjust = 1,
               fill = "white", alpha = 0.8, 
               label.padding = unit(0.2, "lines"), label.size = 0.3) +
    scale_color_viridis_c(
      option = color_palette,
      limits = color_limits,
      name = "Sensor position\nangular\ndivergence (°)",
      direction = -1,
      na.value = "grey50"
    ) +
    coord_polar(theta = "x", start = 0, direction = 1) +
    scale_y_continuous(limits = c(0, 89), breaks = seq(0, 90, 30),
                      expand = c(0, 0), labels = NULL) +
    scale_x_continuous(limits = c(0, 2*pi), breaks = seq(0, 2*pi, length.out = 9),
                      labels = c("N", "NE", "E", "SE", "S", "SW", "W", "NW", ""),
                      expand = c(0, 0)) +
    labs(title = title, y = NULL, x = NULL) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 12, hjust = 0.5),
      legend.position = "right",
      panel.grid.major = element_line(color = "gray70", linewidth = 0.3,
                                     linetype = "dashed"),
      axis.text.x = element_text(size = 8),
      axis.text.y = element_blank(),
      axis.title.y = element_blank()
    )
  
  # Add faceting
  if (!is.null(facet_by)) {
    p <- p +  #facet_wrap(as.formula(paste("~", facet_by)))
              facet_wrap(as.formula(paste("~", paste0("`", facet_by, "`"))))
  }
  
  return(p)
}

# =============================================================================
# PLOT 3: ANGULAR DIVERGENCE HISTOGRAM
# =============================================================================

create_angdiv_histogram <- function(footprints, color_palette = "turbo", 
                                   color_limits = c(0, 100)) {
  
  ang_data <- footprints %>%
    filter(!is.na(ang_div))
  
  if (nrow(ang_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  mean_val <- mean(ang_data$ang_div, na.rm = TRUE)
  median_val <- median(ang_data$ang_div, na.rm = TRUE)
  
  # Create binned data for coloring
  ang_data_binned <- ang_data %>%
    mutate(bin = cut(ang_div, breaks = 30, include.lowest = TRUE)) %>%
    group_by(bin) %>%
    mutate(bin_midpoint = mean(ang_div, na.rm = TRUE)) %>%
    ungroup()
  
  p <- ggplot(ang_data_binned, aes(x = ang_div)) +
    geom_histogram(aes(fill = after_stat(x)), bins = 30, color = "black", size = 0.2) +
    coord_cartesian(xlim = color_limits) + 
    # geom_vline(xintercept = mean_val, color = "red", linetype = "dashed", 
    #            size = 1, alpha = 0.8) +
    geom_vline(xintercept = median_val, color = "black", linetype = "dashed", 
               size = 1, alpha = 0.8) +
    scale_fill_viridis_c(
      option = color_palette,
      limits = color_limits,
      guide = "none",
    direction = -1  # Reverse the color scale
    ) +
    # annotate("text", x = mean_val, y = Inf, 
    #          label = sprintf("Mean: %.1f°", mean_val),
    #          hjust = -0.1, vjust = 1.5, size = 3, color = "red") +
    annotate("text", x = median_val, y = Inf, 
             label = sprintf("Median: %.1f°", median_val),
             hjust = 1.1, vjust = 1.5, size = 3, color = "black") +
    labs(
      x = "Angular Divergence (°)",
      y = "Count",
      title = "Sensor position\nrelative to sun position"
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      panel.grid.minor = element_blank(),
      axis.text = element_text(size = 9)
    )
  
  return(p)
}

# =============================================================================
# PLOT 4: OFF-NADIR HISTOGRAM
# =============================================================================

create_offnadir_histogram <- function(footprints) {
  
  off_data <- footprints %>%
    filter(!is.na(offnadir))
  
  if (nrow(off_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  mean_val <- mean(off_data$offnadir, na.rm = TRUE)
  median_val <- median(off_data$offnadir, na.rm = TRUE)
  
  p <- ggplot(off_data, aes(x = offnadir, fill=sensor)) +
    geom_histogram(bins = 20, 
                   #fill = "coral", 
                   alpha = 0.7, 
                   color = "black", size = 0.2) +
    scale_fill_manual(values = sensor_colors, guide = "none") +
    # geom_vline(xintercept = mean_val, color = "red", linetype = "dashed", 
    #            size = 1, alpha = 0.8) +
    geom_vline(xintercept = median_val, color = "black", linetype = "dashed", 
               size = 1, alpha = 0.8) +
    # annotate("text", x = mean_val, y = Inf, 
    #          label = sprintf("Mean: %.1f°", mean_val),
    #          hjust = -0.1, vjust = 1.5, size = 3, color = "red") +
    annotate("text", x = median_val, y = Inf, 
             label = sprintf("Median: %.1f°", median_val),
             hjust = -0.1, vjust = 1.5, size = 3, color = "black") +
    labs(
      x = "Off-Nadir Angle (°)",
      y = "Count",
      title = "Off-Nadir Distribution"
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      panel.grid.minor = element_blank()
    )
  
  return(p)
}

# =============================================================================
# PLOT 5: DAY OF YEAR WITH JULY/AUGUST BOUNDS
# =============================================================================

create_doy_plot <- function(footprints, title = "Seasonal Distribution") {
  
  doy_data <- footprints %>%
    filter(!is.na(doy))
  
  if (nrow(doy_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  # July and August bounds
  july_start <- 182
  july_end <- 212
  aug_start <- 213
  aug_end <- 243
  
  # Count summer acquisitions
  july_count <- sum(doy_data$doy >= july_start & doy_data$doy <= july_end)
  aug_count <- sum(doy_data$doy >= aug_start & doy_data$doy <= aug_end)
  summer_count <- july_count + aug_count
  summer_pct <- summer_count / nrow(doy_data) * 100
  
  p <- ggplot(doy_data, aes(x = doy, fill=sensor)) +
    # # Shaded regions for July and August
    # annotate("rect", 
    #          xmin = july_start, xmax = july_end,
    #          ymin = 0, ymax = Inf,
    #          fill = "orange", alpha = 0.15) +
    # annotate("rect", 
    #          xmin = aug_start, xmax = aug_end,
    #          ymin = 0, ymax = Inf,
    #          fill = "red", alpha = 0.15) +
    # Histogram
    geom_histogram(bins = 52, color = "black", size = 0.2) +
    # scale_fill_gradientn(
    #   colors = viridis::turbo(100),
    #   guide = "none"
    # ) +
    scale_fill_manual(values = sensor_colors, guide = "none") +
    # # July bounds (dashed lines)
    # geom_vline(xintercept = july_start, color = "orange", 
    #            linetype = "dashed", size = 1.2, alpha = 0.9) +
    # geom_vline(xintercept = july_end, color = "orange", 
    #            linetype = "dashed", size = 1.2, alpha = 0.9) +
    # # August bounds (dashed lines)
    # geom_vline(xintercept = aug_start, color = "red", 
    #            linetype = "dashed", size = 1.2, alpha = 0.9) +
    # geom_vline(xintercept = aug_end, color = "red", 
    #            linetype = "dashed", size = 1.2, alpha = 0.9) +
    # # Labels
    # annotate("text", x = july_start, y = Inf, label = "Jul 1",
    #          hjust = -0.1, vjust = 1.5, size = 2.5, color = "orange") +
    # annotate("text", x = aug_end, y = Inf, label = "Aug 31",
    #          hjust = 1.1, vjust = 1.5, size = 2.5, color = "red") +
    scale_x_continuous(
      limits = c(0, 365),
      breaks = seq(0, 365, by = 30)
    ) +
    labs(
      x = "Day of Year",
      y = "Count",
      title = title
      #, subtitle = sprintf("%.1f%% in Jul-Aug (n=%d)", summer_pct, summer_count)
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      plot.subtitle = element_text(size = 9, hjust = 0.5),
      panel.grid.minor = element_blank(),
      axis.text = element_text(size = 8)
    )
  
  return(p)
}

# =============================================================================
# PLOT 6: TEMPORAL DISTRIBUTION (by month)
# =============================================================================

create_temporal_plot <- function(footprints, title = "Temporal Distribution") {
  
  if (!('date' %in% names(footprints)) || all(is.na(footprints$date))) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  temporal_data <- footprints %>%
    filter(!is.na(date)) %>%
    mutate(year_month = floor_date(date, "month")) %>%
    mutate(year_ = floor_date(date, "year")) %>%
    group_by(sensor, year_) %>%
    summarize(
        n = n()
        )
    #count(year_)
  
  p <- ggplot(temporal_data, aes(x = year_, y = n, fill=sensor)) +
    geom_col(
        #fill = "gray", 
        alpha = 0.7, color = "black", size = 0.2) +
    scale_fill_manual(values = sensor_colors, guide = "none") +
    labs(
      x = "Date",
      y = "Count",
      title = title
    ) +
    #scale_x_date(date_labels = "%Y-%m", date_breaks = "6 months") +
    scale_x_date(date_labels = "%Y", date_breaks = "1 year") +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      axis.text.x = element_text(angle = 45, hjust = 1, size = 8),
      panel.grid.minor = element_blank()
    )
  
  return(p)
}

# =============================================================================
# PLOT 7: SENSOR DISTRIBUTION
# =============================================================================

create_sensor_plot <- function(footprints, title = "Sensor Distribution") {
  
  if (!('sensor' %in% names(footprints))) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  sensor_data <- footprints %>%
    count(sensor) %>%
    arrange(desc(n))
  
  p <- ggplot(sensor_data, aes(x = reorder(sensor, n), y = n, fill = sensor)) +
    geom_col(alpha = 0.7, color = "black", size = 0.3) +
    geom_text(aes(label = format(n, big.mark = ",")), 
              hjust = -0.2, size = 3, fontface = "bold") +
    scale_fill_manual(values = sensor_colors, guide = "none") +
    coord_flip() +
    labs(
      x = "Sensor",
      y = "Count",
      title = title
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      panel.grid.minor = element_blank(),
      axis.text = element_text(size = 9)
    )
  
  return(p)
}

# =============================================================================
# PLOT 8: SUN ELEVATION HISTOGRAM
# =============================================================================

create_sunel_histogram <- function(footprints, title = "Sun Elevation") {
  
  sunel_data <- footprints %>%
    filter(!is.na(sunel))
  
  if (nrow(sunel_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  mean_val <- mean(sunel_data$sunel, na.rm = TRUE)
  median_val <- median(sunel_data$sunel, na.rm = TRUE)
  
  p <- ggplot(sunel_data, aes(x = sunel, fill=sensor)) +
    geom_histogram(bins = 20, 
                   #fill = "gold", 
                   alpha = 0.7, 
                   color = "black", size = 0.2) +
    scale_fill_manual(values = sensor_colors, guide = "none") +
    geom_vline(xintercept = median_val, color = "black", 
               linetype = "dashed", size = 1) +
    annotate("text", x = median_val, y = Inf, 
             label = sprintf("Median: %.1f°", median_val),
             hjust = -0.1, vjust = 1.5, size = 3, color = "black") +
    labs(
      x = "Sun Elevation (°)",
      y = "Count",
      title = title
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      panel.grid.minor = element_blank()
    )
  
  return(p)
}

# =============================================================================
# PLOT 9: VIEW ELEVATION HISTOGRAM
# =============================================================================

create_viewel_histogram <- function(footprints, title = "View Elevation") {
  
  viewel_data <- footprints %>%
    filter(!is.na(el))
  
  if (nrow(viewel_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  median_val <- median(viewel_data$el, na.rm = TRUE)
  
  p <- ggplot(viewel_data, aes(x = el, fill=sensor)) +
    geom_histogram(bins = 20, 
                   #fill = "skyblue", 
                   alpha = 0.7, 
                   color = "black", size = 0.2) +
    scale_fill_manual(values = sensor_colors, guide = "none") +
    geom_vline(xintercept = median_val, color = "black", 
               linetype = "dashed", size = 1) +
    annotate("text", x = median_val, y = Inf, 
             label = sprintf("Median: %.1f°", median_val),
             hjust = -0.1, vjust = 1.5, size = 3, color = "black") +
    labs(
      x = "View Elevation (°)",
      y = "Count",
      title = title
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      panel.grid.minor = element_blank()
    )
  
  return(p)
}

# =============================================================================
# PLOT 9: GSD HISTOGRAM
# =============================================================================

create_gsd_histogram <- function(footprints, title = "Ground Sample Distance", fill_var = "sensor") {
  
  gsd_data <- footprints %>%
    filter(!is.na(gsd))
  
  if (nrow(gsd_data) == 0) {
    return(ggplot() + annotate("text", x = 0, y = 0, label = "No data") + theme_void())
  }
  
  median_val <- median(gsd_data$gsd, na.rm = TRUE)
  
  # Check if fill_var exists in the data
  if (!fill_var %in% names(gsd_data)) {
    warning(paste("Column", fill_var, "not found. Using default fill."))
    p <- ggplot(gsd_data, aes(x = gsd)) +
      geom_histogram(bins = 20, fill = "skyblue", alpha = 0.7, color = "black", size = 0.2)
  } else {
    p <- ggplot(gsd_data, aes(x = gsd, fill = .data[[fill_var]])) +
      geom_histogram(bins = 20, alpha = 0.7, color = "black", size = 0.2) +
      scale_fill_manual(values = sensor_colors, guide = "none")
  }
  
  p <- p +
    geom_vline(xintercept = median_val, color = "black", 
               linetype = "dashed", size = 1) +
    annotate("text", x = median_val, y = Inf, 
             label = sprintf("Median: %.1f°", median_val),
             hjust = -0.1, vjust = 1.5, size = 3, color = "black") +
    labs(
      x = "Ground Sample Distance (m)",
      y = "Count",
      title = title
    ) +
    theme_minimal() +
    theme(
      plot.title = element_text(face = "bold", size = 11, hjust = 0.5),
      panel.grid.minor = element_blank()
    )
  
  return(p)
}
# =============================================================================
# CREATE DASHBOARD USING PATCHWORK
# =============================================================================

create_dashboard <- function(footprints, main_title = "VHR Acquisition Dashboard") {
  
  cat("Creating dashboard plots...\n")
  
  # Create individual plots
  p_map <- create_overview_map(footprints)
  p_polar <- create_polar_plot(footprints)
  p_angdiv <- create_angdiv_histogram(footprints)
  p_offnadir <- create_offnadir_histogram(footprints)
  p_doy <- create_doy_plot(footprints)
  p_temporal <- create_temporal_plot(footprints)
  p_sensor <- create_sensor_plot(footprints)
  p_sunel <- create_sunel_histogram(footprints)
  p_gsd <- create_gsd_histogram(footprints)
  
  # Assemble dashboard using patchwork
  # Layout:
  # Row 1: Map (2 units) | Polar (2 units)
  # Row 2: AngDiv | OffNadir | SunEl | ViewEl
  # Row 3: DOY (2 units) | Temporal | Sensor
  
  dashboard <- (p_map | p_polar) /
               (p_angdiv | p_offnadir | p_sunel | p_gsd) /
               (p_doy | (p_temporal / p_sensor)) +
    plot_annotation(
      title = main_title,
      theme = theme(
        plot.title = element_text(size = 18, face = "bold", hjust = 0.5)
      )
    )
  
  return(dashboard)
}

# =============================================================================
# ALTERNATIVE COMPACT LAYOUT
# =============================================================================

create_dashboard_compact <- function(footprints, main_title = "VHR Summary") {
  
  # Create plots
  p_map <- create_overview_map(footprints)
  p_polar <- create_polar_plot(footprints)
  p_angdiv <- create_angdiv_histogram(footprints)
  p_doy <- create_doy_plot(footprints)
  p_sensor <- create_sensor_plot(footprints)
  
  # Compact layout: 2 rows
  dashboard <- (p_map | p_polar) /
               (p_angdiv | p_doy | p_sensor) +
    plot_annotation(
      title = main_title,
      theme = theme(plot.title = element_text(size = 16, face = "bold", hjust = 0.5))
    )
  
  return(dashboard)
}

create_dashboard_custom <- function(footprints, zoom=FALSE, main_title = "Acquisition metadata of spaceborne VHR images", facet_by=NULL) {
  
  cat("Creating dashboard plots...\n")
  
  # Create individual plots
  p_map <- create_overview_map(footprints, zoom=zoom, , zoom_circle_scale = 3)
  p_polar <- create_polar_plot(footprints, facet_by=facet_by)
  p_angdiv <- create_angdiv_histogram(footprints)
  p_offnadir <- create_offnadir_histogram(footprints)
  p_doy <- create_doy_plot(footprints)
  p_temporal <- create_temporal_plot(footprints)
  p_sensor <- create_sensor_plot(footprints)
  p_sunel <- create_sunel_histogram(footprints)
  p_gsd <- create_gsd_histogram(footprints)
  
  # dashboard <- (p_map | p_polar | p_angdiv) /
  #              (p_offnadir | p_sunel | p_gsd) /
  #              (p_doy | (p_temporal / p_sensor)) +
  design <- "
      AABBCC
      AABBCC
      IIIIII
      EEFFGG
      DDHHHH
    "
 dashboard = p_map + p_polar + p_angdiv + p_doy + p_offnadir + p_sunel + p_gsd + p_temporal + p_sensor +
    plot_layout(design = design) +
    plot_annotation(
      title = main_title,
      theme = theme(
        plot.title = element_text(size = 18, face = "bold", hjust = 0)
      )
    )
  
  return(dashboard)
}

######
# Angular divergence
######


compute_unit_vector <- function(elevation, azimuth) {
  # Convert to radians
  elevation_rad <- elevation * pi / 180
  azimuth_rad <- azimuth * pi / 180
  
  # Compute x, y, z using spherical to Cartesian conversion
  x <- cos(elevation_rad) * sin(azimuth_rad)
  y <- cos(elevation_rad) * cos(azimuth_rad)
  z <- sin(elevation_rad)
  
  return(cbind(x, y, z))
}

compute_angular_divergence <- function(sun_vector, view_vector) {
  # Compute dot product
  dot_product <- sum(sun_vector * view_vector)
  
  # Compute angle
  angle <- acos(dot_product)
  
  # Convert to degrees
  return(angle * 180 / pi)
}

get_angular_divergence_column <- function(df, 
                                          cols_rename_dict = c('sunel' = 'sun_elevation', 
                                                              'sunaz' = 'sun_azimuth', 
                                                              'el' = 'view_elevation', 
                                                              'az' = 'view_azimuth')) {
  
  # Compute the angular divergence between the sun and the view direction in degrees.
  
  df_tmp <- df
  
  # Rename columns
  for (old_name in names(cols_rename_dict)) {
    if (old_name %in% names(df_tmp)) {
      names(df_tmp)[names(df_tmp) == old_name] <- cols_rename_dict[old_name]
    }
  }
  
  # Compute unit vectors
  sun_vector <- compute_unit_vector(df_tmp$sun_elevation, df_tmp$sun_azimuth)
  view_vector <- compute_unit_vector(df_tmp$view_elevation, df_tmp$view_azimuth)
  
  # Compute angular divergence for each row
  ang_div_list <- sapply(1:nrow(sun_vector), function(i) {
    compute_angular_divergence(sun_vector[i, ], view_vector[i, ])
  })
  
  # Add to original dataframe
  df$ang_div <- ang_div_list
  
  return(df)
}

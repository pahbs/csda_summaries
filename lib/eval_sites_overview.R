# =============================================================================
# eval_sites_overview.R
#
# Functions to build overview maps from the CSDA Evaluation Sites database.
# Source from any notebook:
#     source('/path/to/eval_sites_overview.R')
# =============================================================================

# Required packages — load once when the library is sourced
suppressPackageStartupMessages({
  library(sf)
  library(dplyr)
  library(ggplot2)
  library(RColorBrewer)
  library(leaflet)        # only for colorFactor (used optionally below)
    library(viridis)
})


# -----------------------------------------------------------------------------
# Load and prepare the sites + base layers
# -----------------------------------------------------------------------------

#' Load the evaluation sites GeoJSON and join to continents
#'
#' @param sites_url  URL or local path to the GeoJSON
#' @param world_path Path to a continents/world shapefile to join against.
#'                   If NULL, attempts rnaturalearth::ne_countries("medium").
#' @return An sf object of sites with continent attributes joined.
load_eval_sites <- function(
  sites_url  = 'https://raw.githubusercontent.com/pahbs/csda_summaries/master/sites/eval_sites_aoi.geojson',
  world_path = '/explore/nobackup/people/pmontesa/userfs02/arc/continents.shp'
) {
  sites_eval <- sf::st_read(sites_url, quiet = TRUE)

  world <- tryCatch(
    rnaturalearth::ne_countries(scale = 'medium', returnclass = 'sf'),
    error = function(e) {
      message('rnaturalearth unavailable, reading continents from local file...')
      sf::st_read(world_path, quiet = TRUE)
    }
  )

  sf::st_join(sites_eval, world, left = TRUE)
}


# -----------------------------------------------------------------------------
# Reproject world + graticule for a given projection
# -----------------------------------------------------------------------------

#' Build base layers (world polygons + graticule) reprojected for plotting
#'
#' @param world_path Path to continents/world shapefile
#' @param proj       PROJ string for the target projection
#' @return List with `world_proj` and `graticule_proj` (both sf)
prep_base_layers <- function(
  world_path = '/explore/nobackup/people/pmontesa/userfs02/arc/continents.shp',
  proj       = '+proj=eck6 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs'
) {
  world <- sf::st_read(world_path, quiet = TRUE)
  original_crs <- sf::st_crs(world)
  if (is.na(original_crs)) original_crs <- 4326

  world_proj <- world %>%
    sf::st_set_crs(original_crs) %>%
    sf::st_cast('MULTILINESTRING') %>%
    sf::st_set_crs(original_crs) %>%
    sf::st_cast('LINESTRING', do_split = TRUE) %>%
    sf::st_set_crs(original_crs) %>%
    sf::st_transform(crs = proj) %>%
    sf::st_cast('POLYGON')

  graticule <- sf::st_graticule(lat = seq(-90, 90, 30),
                                lon = seq(-180, 180, 30))
  graticule_with_continent <- sf::st_join(graticule, world, left = FALSE)
  graticule_proj <- sf::st_transform(graticule_with_continent, crs = proj)

  list(world_proj = world_proj, graticule_proj = graticule_proj)
}


# -----------------------------------------------------------------------------
# Build the empty ggplot base map (graticule + continents, no sites)
# -----------------------------------------------------------------------------

#' Build a base ggplot map with reprojected graticule and continents
#'
#' @param world_proj     sf object — reprojected continents
#' @param graticule_proj sf object — reprojected graticule lines
#' @param proj           PROJ string used for coord_sf
#' @return A ggplot object with no site data yet
build_base_map <- function(world_proj, graticule_proj, proj) {
  ggplot() +
    geom_sf(data = graticule_proj, color = 'lightgray',
            size = 0.2, alpha = 0.5) +
    geom_sf(data = world_proj, fill = 'gray90',
            color = 'gray90', size = 0.1) +
    theme_void() +
    theme(
      panel.background = element_rect(fill = 'white', color = NA),
      plot.background  = element_rect(fill = 'white', color = NA),
      legend.text      = element_text(size = 6),
      legend.title     = element_text(size = 7),
      legend.position  = 'top',
      legend.direction = 'vertical',
      legend.box       = 'vertical'
    ) +
    coord_sf(crs = proj)
}


#' Build a named color vector that locks each Domain to a specific color
#'
#' Supports both ColorBrewer (RColorBrewer) and viridis palettes.
#'
#' @param sites_eval  sf or data.frame with the categorical column
#' @param domain_col  Column name (string) for the categorical variable
#' @param palette     Palette name. ColorBrewer names like 'Spectral', 'Set1',
#'                    'Dark2'. Viridis names: 'viridis', 'magma', 'plasma',
#'                    'inferno', 'cividis', 'mako', 'rocket', 'turbo'.
#' @param source      'auto' (default), 'brewer', or 'viridis'.
#'                    'auto' chooses based on palette name.
#' @return Named character vector mapping category → hex color
build_domain_palette <- function(sites_eval,
                                  domain_col = 'Remote.Sensing.Domain',
                                  palette    = 'Spectral',
                                  source     = c('auto', 'brewer', 'viridis')) {
  source <- match.arg(source)

  cats <- sort(unique(sites_eval[[domain_col]]))
  n    <- length(cats)
  if (n == 0) return(character(0))

  viridis_palettes <- c('viridis', 'magma', 'plasma',
                        'inferno', 'cividis', 'mako',
                        'rocket', 'turbo')

  use <- if (source == 'auto') {
    if (palette %in% viridis_palettes) 'viridis' else 'brewer'
  } else {
    source
  }

  cols <- if (use == 'viridis') {
    if (!requireNamespace('viridisLite', quietly = TRUE)) {
      stop('Install the viridisLite (or viridis) package: ',
           'install.packages("viridisLite")')
    }
    viridisLite::viridis(n, option = palette)
  } else {
    # ColorBrewer path — clamp to palette's max size, ramp if needed
    pal_info <- tryCatch(
      RColorBrewer::brewer.pal.info[palette, ],
      error = function(e) stop('Unknown palette: "', palette, '"')
    )
    max_n <- pal_info$maxcolors

    if (n <= max_n) {
      RColorBrewer::brewer.pal(max(n, 3), palette)[seq_len(n)]
    } else {
      # Interpolate when n exceeds palette's native size
      colorRampPalette(RColorBrewer::brewer.pal(max_n, palette))(n)
    }
  }

  setNames(cols, cats)
}


# -----------------------------------------------------------------------------
# Map builders for specific overviews
# -----------------------------------------------------------------------------

#' Build an overview map of evaluation sites with optional site highlighting
#'
#' @param sites_proj      sf object of sites in the target projection
#' @param base_map        ggplot built by build_base_map()
#' @param my_colors       Named color vector from build_domain_palette()
#' @param domain_col      Column to color points by
#' @param filter_expr     Optional filter expression as a string (e.g.,
#'                          "`Program.Use` == 'CSDA'") — applied to sites_proj
#' @param highlight_sites Optional character vector of site names to color;
#'                          all other sites are drawn in gray.
#'                          NULL = color all sites by domain (default).
#' @param site_col        Column holding the site identifier (default 'Site.Name')
#' @param gray_color      Color used for non-highlighted sites (default 'gray70')
#' @param title           Plot title
#' @param legend_title    Legend title
#' @return A ggplot object
build_overview_map <- function(sites_proj, base_map, my_colors,
                               domain_col      =  'Evaluation.Category',#'Remote.Sensing.Domain',
                               filter_expr     = NULL,
                               highlight_sites = NULL,
                               label_sites = NULL,
                               site_col        = 'Site.Name',
                               gray_color      = 'gray70',
                               title           = 'Evaluation Sites',
                               legend_title    = NULL #'SME Domain '
                              ) {

  data <- if (!is.null(filter_expr)) {
    dplyr::filter(sites_proj, !!rlang::parse_expr(filter_expr))
  } else {
    sites_proj
  }

  if (!is.null(highlight_sites)) {
    # Split into highlighted vs. faded
    sites_color <- dplyr::filter(data, .data[[site_col]] %in% highlight_sites)
    sites_gray  <- dplyr::filter(data, !(.data[[site_col]] %in% highlight_sites))

    overview_map = base_map +
      # Faded background sites
      geom_point(
        data = sites_gray,
        aes(geometry = geometry),
        stat = 'sf_coordinates',
        shape = 21, size = 1.2, fill = gray_color,
        color = 'gray50', stroke = 0.2, alpha = 0.6
      ) +
      # Highlighted colored sites on top
      geom_point(
        data = sites_color,
        aes(geometry = geometry, fill = .data[[domain_col]]),
        stat = 'sf_coordinates',
        shape = 21, size = 2.0, color = 'red', stroke = 0.4
      ) +
      scale_fill_manual(
        values = my_colors, drop = FALSE,
        name = legend_title,
        guide = guide_legend(
          nrow = 1,
          override.aes = list(size = 3, label = '')
        )
      ) +
      labs(title = title,
           subtitle = paste(highlight_sites, collapse=', '),
           caption = sprintf('%d of %d sites', nrow(sites_color), nrow(data)))

  } else {
    # Default: all sites colored by domain
    overview_map = base_map +
      geom_point(
        data = data,
        aes(geometry = geometry, fill = .data[[domain_col]]),
        stat = 'sf_coordinates',
        shape = 21, size = 1.5, color = 'black', stroke = 0.3
      ) +
      scale_fill_manual(
        values = my_colors, drop = FALSE,
        name = legend_title,
        guide = guide_legend(
          nrow = 1,
          override.aes = list(size = 3, label = '')
        )
      ) +
      labs(title = title)
  }

  if (!is.null(label_sites)) {
    overview_map = overview_map + geom_label_repel(data = dplyr::filter(data, .data[[site_col]] %in% label_sites), aes(label=.data[[site_col]]))  
      } else {
      overview_map
  }
}


#' Build an overview map of priority sites colored by Evaluation Category
#'
#' @param sites_proj   sf object in target projection
#' @param base_map     ggplot built by build_base_map()
#' @param priority     Priority level to filter on (default 'high')
#' @param title        Plot title
#' @return A ggplot object
build_priority_map <- function(sites_proj, base_map,
                               priority = 'high',
                               title    = 'CSDA Priority Sites') {
  base_map +
    # geom_point(
    #   data = dplyr::filter(sites_proj, `Priority.Level` == priority),
    #   aes(color = `Evaluation.Category`),
    #   size = 1, shape = 1
    # ) +
      geom_point(
        data = dplyr::filter(sites_proj, `Priority.Level` == priority),
        aes(geometry = geometry, fill = `Evaluation.Category`),
        stat = 'sf_coordinates',
        shape = 21, size = 1.5, color = 'black', stroke = 0.3
      ) +
    scale_fill_brewer(
      palette = 'Dark2',
      name = title,
      guide = guide_legend(
        ncol = 3,
        override.aes = list(size = 5, label = '')
      )
    )
}


# -----------------------------------------------------------------------------
# One-call convenience wrapper
# -----------------------------------------------------------------------------

#' Build all overview maps in one call
#'
#' @param sites_url  URL or path to GeoJSON
#' @param world_path Path to continents shapefile
#' @param proj       PROJ string for plotting projection
#' @return List with maps and intermediate objects:
#'   $sites_proj, $base_map, $my_colors,
#'   $map_csda, $map_fusion, $map_priority
make_eval_site_overview <- function(
  sites_url  = 'https://raw.githubusercontent.com/pahbs/csda_summaries/master/sites/eval_sites_aoi.geojson',
  world_path = '/explore/nobackup/people/pmontesa/userfs02/arc/continents.shp',
  proj       = '+proj=eck6 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs',
    highlight_sites = NULL,
    label_sites = NULL
) {
  sites_eval <- load_eval_sites(sites_url, world_path)
  base       <- prep_base_layers(world_path, proj)
  sites_proj <- sf::st_transform(sites_eval, crs = proj)

  my_colors <- build_domain_palette(sites_eval, 'Remote.Sensing.Domain')
  my_colors_evaLcat <- build_domain_palette(sites_eval, 'Evaluation.Category', palette='inferno')
  base_map  <- build_base_map(base$world_proj, base$graticule_proj, proj)

  list(
    sites_proj   = sites_proj,
    base_map     = base_map,
    my_colors    = my_colors,
    map_csda = build_overview_map(sites_proj, base_map, my_colors,
                                   filter_expr = "`Program.Use` == 'CSDA'",
                                   highlight_sites = highlight_sites, label_sites = label_sites,
                                   title = 'CSDA Evaluation Sites',
                                   legend_title = NULL),
    map_csda_sme_domain = build_overview_map(sites_proj, base_map, my_colors,
                                   filter_expr = "`Program.Use` == 'CSDA'",
                                   highlight_sites = highlight_sites, label_sites = label_sites,
                                   title = 'CSDA Evaluation Sites', domain_col =  'Remote.Sensing.Domain',
                                   legend_title = NULL),
    map_csda_eval_cat = build_overview_map(sites_proj, base_map, my_colors_evaLcat,
                                   filter_expr = "`Program.Use` == 'CSDA'",
                                   highlight_sites = highlight_sites, label_sites = label_sites,
                                   title = 'CSDA Evaluation Sites', domain_col =  'Evaluation.Category',
                                   legend_title = NULL),
    map_fusion   = build_overview_map(sites_proj, base_map, my_colors,
                                      title = 'SLI-FUSION Evaluation Sites',
                                      legend_title = 'SME Domain ')
    # map_priority = build_priority_map(sites_proj, base_map,
    #                                   priority = 'high',
    #                                   title = 'CSDA Priority Sites ')
  )
}
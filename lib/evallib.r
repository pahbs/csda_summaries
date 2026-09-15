# Custom functions to read a variety of CSV files associated with CSDA Evaluation Results

# [1] Output from radiometric and geometric teams
# [2] RSR files from various sensors associated with evaluations

read_evaluation_files <- function(files_list){

    ACQ_COLS <- c(
      'evaluation_category','evaluation_type', 'vendor', 'affiliation', 'constellation', 'satellite',
      'site_name', 'product_level',
      'acq_datetime', 
        #'date', 
        'source_file'
        )
    
    # Band order defined inside function so it's always available
    band_order <- c(
        'Pan', 'Coastal', 'CB', 'Blue', 'B', 'Green', 'G', 'Yellow', 'Y', 
        'Red', 'R', 'RedEdge', 'RE', 'RedEdge1', 'RE1', 'RedEdge2', 'RE2', 
        'NIR', 'NIR1', 'NIR2', 'SWIR1', 'SWIR2'
    )

    df = files_list %>%
            set_names() %>%
            map_df(read_csv, .id = "source_file", show_col_types=FALSE) %>%
            mutate(
            evaluation_category = if_else(
              grepl("radiometric", source_file, ignore.case = TRUE), 
              "radiometric", 
              "geometric"
            )
          ) %>%
            
            # Drop empty unnamed trailing columns
            select(-matches("^\\.\\.\\.\\d+$")) %>%
            select(where(~ !all(is.na(.x)))) %>%
            
            # Standardize column names
            rename_with(~ case_when(
                .x == "Evaluation Type" ~ "Evaluation_type",
                TRUE                    ~ .x
            )) %>%
            rename_with(tolower) %>%
            
            # # Add missing common acquisition cols as NA
            # { if (!"Date_time_in_UTC(YYYYMMDD_HHMMSS)" %in% names(.))
            #     mutate(., `Date_time_in_UTC(YYYYMMDD_HHMMSS)` = NA_character_) else . } %>%
            # { if (!"Time_series_date_min(YYYYMMDD)" %in% names(.))
            #     mutate(., `Time_series_date_min(YYYYMMDD)` = NA_character_) else . } %>%
            # { if (!"Time_series_date_max(YYYYMMDD)" %in% names(.))
            #     mutate(., `Time_series_date_max(YYYYMMDD)` = NA_character_) else . } %>%
            { if (!"acq_datetime" %in% names(.))
                mutate(., acq_datetime = NA_character_) else . } %>%
            { if (!"acq_id" %in% names(.))
                mutate(., acq_id = NA_character_) else . } %>%
            { if (!"satellite" %in% names(.))
                mutate(., satellite = NA_character_) else . } %>%
            { if (!"band_name" %in% names(.))
                mutate(., band_name = NA_character_) else . } %>%
             
            { if ("vendor" %in% names(.))
                mutate(., affiliation = vendor) %>% select(-vendor) else . } %>%
            
            mutate(
                # KEY FIX: convert acq_datetime to character first
                # so it's always a string going into parse_date_time
                # regardless of how read_csv interpreted it
                acq_datetime = case_when(
                    !is.na(acq_datetime) ~
                        parse_date_time(as.character(acq_datetime),
                                       orders = c('YmdHMS', 'Ymd HMS',
                                                  'Y-m-d H:M:S', 'Y-m-d',
                                                  'Ymd',
                                                  'mdy',        # ADD: handles 11/3/2024
                                                  'mdY',        # ADD: handles 11/03/2024
                                                  'dmy'),       # ADD: handles European format
                                       tz = 'UTC'),
                    !is.na(acq_datetime) ~
                        parse_date_time(acq_datetime,
                                       orders = 'YmdHMS',
                                       tz = 'UTC'),
                    TRUE ~ NA_POSIXct_
                ),
                affiliation = str_to_title(affiliation),
                constellation = str_to_title(constellation),
                .keep = "unused"
            ) %>%
            mutate(
                band_name = factor(band_name, levels = band_order),
                satellite = factor(satellite)
            ) %>%
            relocate(any_of(ACQ_COLS), .before = everything()) %>%
            relocate(source_file, .after = last_col()) %>%
            filter(if_any(-source_file, ~ !is.na(.))) # Removes extra rows that are just NA

    return(df)
}

read_maxar_legacy_rsr <- function(file_path) {
  
  # ── Read raw lines to extract band names from header ─────────────────────────
  lines     <- readLines(file_path, warn = FALSE)
  
  # ── Row 1: band names (split on whitespace, drop first element "BAND") ───────
  band_names <- str_split(lines[1], "\\s+")[[1]] %>%
    str_trim() %>%
    .[. != ""] %>%   # drop any empty strings from leading whitespace
    .[-1]            # drop "BAND" / "WL" label
  
  # ── Read data rows (skip header row 1) ───────────────────────────────────────
  df <- read_table(
    file_path,
    skip           = 1,
    col_names      = c("wavelength_nm", band_names),
    col_types      = cols(.default = col_double()),
    show_col_types = FALSE
  )
  
  # ── Convert wavelength if needed (micrometers → nanometers) ──────────────────
  if (min(df$wavelength_nm, na.rm = TRUE) < 50) {
    df <- df %>% mutate(wavelength_nm = wavelength_nm * 1000)
  }
  
  # ── Pivot to long format ──────────────────────────────────────────────────────
  df <- df %>%
    pivot_longer(
      cols           = -wavelength_nm,
      names_to       = "band",
      values_to      = "rsr",
      values_drop_na = FALSE
    ) %>%
    # ── Standardize band names ──────────────────────────────────────────────────
    mutate(
      band = str_trim(band),
      band = case_when(
        str_detect(band, "(?i)^pan$")                     ~ "Pan",
        str_detect(band, "(?i)coastal")                   ~ "Coastal",
        str_detect(band, "(?i)^blue$")                    ~ "Blue",
        str_detect(band, "(?i)^green$")                   ~ "Green",
        str_detect(band, "(?i)^yellow$")                  ~ "Yellow",
        str_detect(band, "(?i)rededge|red.edge|red-edge") ~ "RedEdge",
        str_detect(band, "(?i)^red$")                     ~ "Red",
        str_detect(band, "(?i)nir1")                      ~ "NIR1",
        str_detect(band, "(?i)nir2")                      ~ "NIR2",
        str_detect(band, "(?i)^nir$")                     ~ "NIR",
        TRUE ~ str_to_title(band)
      )
    )
  
  # ── Extract sensor name from filename ─────────────────────────────────────────
  # e.g. "BandPass_WorldView-2_RSR.txt" -> "WorldView-2"
  filename   <- basename(file_path)
  sensor_raw <- str_extract(filename, "(?<=BandPass_).+?(?=_RSR|_rsr|\\.txt$)") %>%
    str_trim()
  if (is.na(sensor_raw)) sensor_raw <- str_remove(filename, "\\.txt$")
  
  # ── Infer constellation ───────────────────────────────────────────────────────
  constellation <- case_when(
    str_detect(sensor_raw, "(?i)worldview")  ~ "WorldView",
    str_detect(sensor_raw, "(?i)geoeye")     ~ "GeoEye",
    str_detect(sensor_raw, "(?i)quickbird")  ~ "QuickBird",
    str_detect(sensor_raw, "(?i)ikonos")     ~ "IKONOS",
    TRUE ~ sensor_raw
  )
  
  df <- df %>%
    mutate(
      sensor        = sensor_raw,
      affiliation   = "Maxar",
      constellation = constellation
    )
  
  return(df)
}

# Helper function to read and normalize Planet RSR files
read_planet_rsr <- function(file_path) {
  # Read the file
  df <- read_csv(file_path, show_col_types = FALSE)
  
  # Get the filename for sensor extraction
  filename <- basename(file_path)
  
  # Standardize column names - rename first column to wavelength
  df <- df %>%
    rename_with(~"wavelength", 1) %>%
    rename_all(tolower)
  
  # Convert wavelength to nm if needed
  # If wavelengths are small (< 50), assume micrometers; if >= 200, assume nanometers
  if (min(df$wavelength, na.rm = TRUE) < 50) {
    df <- df %>% mutate(wavelength = wavelength * 1000)
  }
  df <- df %>% rename(wavelength_nm = wavelength)
  
  # Pivot to long format, keeping wavelength_nm and pivoting spectral bands
  df <- df %>%
    pivot_longer(
      cols = -wavelength_nm,
      names_to = "band",
      values_to = "rsr",
      values_drop_na = FALSE
    ) %>%
    # Clean up band names - remove extra text and spaces
    mutate(
      band = str_trim(band),
      band = str_replace_all(band, "_i i", ""),
      band = str_replace_all(band, "_i$", ""),
      band = str_replace_all(band, " response$", ""),
      band = str_replace_all(band, "-blue", ""),
      band = case_when(
        str_detect(band, "blue") ~ "Blue",
          str_detect(band, "coastal") ~ "Coastal",
        str_detect(band, "green_i") ~ "Green",
          str_detect(band, "green_ii") ~ "Green1",
        str_detect(band, "yellow") ~ "Yellow",
        str_detect(band, "red edge|red-edge") ~ "RedEdge",
        str_detect(band, "^red$") ~ "Red",
        str_detect(band, "nir|near") ~ "NIR",
        str_detect(band, "^pan$") ~ "Pan",
        TRUE ~ str_to_title(band)
      )
    )
  
  # Extract sensor and constellation from filename
  sensor_info <- case_when(
    str_detect(filename, "dove_r|Dove") ~ list(sensor = "Dove-R", constellation = "Dove-R"),
    str_detect(filename, "PlanetScope|planetscope") ~ {
      sat_id <- str_extract(filename, "(?<=SatID_)[0-9a-fA-F]+")
      if (is.na(sat_id)) sat_id <- "PlanetScope"
      list(sensor = paste0("PlanetScope_", sat_id), constellation = "Dove-Classic")
    },
    str_detect(filename, "RapidEye") ~ list(sensor = "RapidEye", constellation = "RapidEye"),
      str_detect(filename, "Skysat|SkySat") ~ {
          # Extract all numbers that follow any "skysat" string (case-insensitive)
          nums <- str_extract_all(filename, "(?i)(?<=skysat)\\d+")[[1]]
          
          if (length(nums) >= 2) {
            sensor_name <- paste0("SkySat ", nums[1], "-", nums[2])  # e.g. "SkySat 14-19"
          } else if (length(nums) == 1) {
            sensor_name <- paste0("SkySat ", nums[1])                 # e.g. "SkySat 4"
          } else {
            sensor_name <- "SkySat"                                   # fallback
          }
          list(sensor = sensor_name, constellation = "SkySat")
        },
    str_detect(filename, "Superdove") ~ list(sensor = "SuperDove", constellation = "SuperDove"),
    TRUE ~ list(sensor = str_remove(filename, "\\.csv$"), constellation = "Planet")
  )
  
  df <- df %>%
    mutate(
      sensor = sensor_info$sensor,
      affiliation = "Planet",
      constellation = sensor_info$constellation
    )
  
  return(df)
}
# {{dataset}}: variables selected with survey-merge on {{created}}.
#
# Run this from the folder that holds README.md: open the .Rproj file in
# RStudio and source this script, or run `Rscript R/merge.R` from a terminal.
# README.md lists the data files it needs.

# ── Settings ─────────────────────────────────────────────────────────────

# The folder holding the data files. Subfolders are searched too.
DATA_DIR <- "data"

# Where the results are written.
OUTPUT_DIR <- "output"

# TRUE replaces each variable's missing-value codes below with NA.
# FALSE keeps the codes exactly as deposited.
MISSING_TO_NA <- {{missing_to_na}}

# The column that identifies a person in every file.
IDENTIFIER <- "{{identifier}}"

# ── Your selection ───────────────────────────────────────────────────────

# For each data file, the variables to take from it:
#   output_column = "variable name in the file"
SELECTION <- list(
{{selection}}
)

# The codes MISSING_TO_NA replaces, per output column: single values, and
# ranges as c(low, high) where NA is an open end. Taken from the data
# dictionary: the declared missing values plus any labelled negative code.
MISSING_CODES <- list(
{{missing_codes}}
)

# ── Merge ────────────────────────────────────────────────────────────────

source(file.path("R", "load_data.R"))

index <- index_data_dir(DATA_DIR)

# Check every file is present before reading any of them.
paths <- vapply(names(SELECTION), function(f) find_data_file(index, f), character(1))
if (anyNA(paths)) {
  stop(
    "These data files were not found under ", normalizePath(DATA_DIR, mustWork = FALSE), ":\n",
    paste0("  ", names(paths)[is.na(paths)], collapse = "\n"),
    "\nSee README.md for where to get them.",
    call. = FALSE
  )
}

dir.create(OUTPUT_DIR, showWarnings = FALSE, recursive = TRUE)
wide <- list()

for (file in names(SELECTION)) {
  wanted <- SELECTION[[file]]
  message("Reading ", basename(paths[[file]]))
  got <- read_columns(paths[[file]], c(IDENTIFIER, unname(wanted)))
  if (IDENTIFIER %in% got$missing) {
    stop(file, " has no ", IDENTIFIER, " column, so it cannot be merged.", call. = FALSE)
  }
  if (length(got$missing) > 0) {
    warning(file, ": not found, skipped: ", paste(got$missing, collapse = ", "), call. = FALSE)
  }

  keep <- wanted[wanted %in% names(got$data)]
  data <- got$data[, c(IDENTIFIER, unname(keep)), drop = FALSE]
  names(data) <- c(IDENTIFIER, names(keep))
  data[[IDENTIFIER]] <- normalise_identifier(data[[IDENTIFIER]])
  if (MISSING_TO_NA) {
    for (column in names(keep)) {
      data[[column]] <- apply_missing_codes(data[[column]], MISSING_CODES[[column]])
    }
  }

  # A file with more than one row per person (a household grid, a history)
  # cannot be joined one-to-one. It is written out on its own instead.
  data <- unique(data)
  if (anyDuplicated(data[[IDENTIFIER]]) > 0) {
    out <- file.path(OUTPUT_DIR, paste0(file, "_long.csv"))
    utils::write.csv(data, out, row.names = FALSE, na = "")
    message(file, " has several rows per ", IDENTIFIER, "; written separately to ", out)
    next
  }
  wide[[file]] <- data
}

if (length(wide) > 0) {
  merged <- Reduce(function(a, b) merge(a, b, by = IDENTIFIER, all = TRUE), wide)
  out <- file.path(OUTPUT_DIR, "merged.csv")
  utils::write.csv(merged, out, row.names = FALSE, na = "")
  message("Wrote ", nrow(merged), " rows and ", ncol(merged), " columns to ", out)
}

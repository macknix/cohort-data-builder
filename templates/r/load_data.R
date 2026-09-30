# Reading deposited data files, for merge.R.
#
# Nothing in here names a study: merge.R says which files and variables it
# wants, and this finds and reads them. The read call is chosen from each
# file's extension, so it works with whichever format you downloaded from the
# UK Data Service:
#
#   .tab .txt .dat   tab-delimited      base R
#   .csv             comma-separated    base R
#   .dta             Stata              haven
#   .sav .zsav       SPSS               haven
#
# Files are found by name anywhere under the data folder, subfolders included,
# so a UKDS download can be unzipped into it as it is. Every file is opened
# for reading only.

supported_formats <- c("tab", "txt", "dat", "csv", "dta", "sav", "zsav")

# Every readable file under data_dir, grouped by lower-case name without its
# extension.
index_data_dir <- function(data_dir) {
  if (!dir.exists(data_dir)) {
    stop(
      "The data folder does not exist: ", normalizePath(data_dir, mustWork = FALSE),
      "\nPut the data files there, or set DATA_DIR at the top of merge.R.",
      call. = FALSE
    )
  }
  paths <- list.files(data_dir, recursive = TRUE, full.names = TRUE)
  ext <- tolower(tools::file_ext(paths))
  paths <- paths[ext %in% supported_formats]
  split(paths, tolower(tools::file_path_sans_ext(basename(paths))))
}

# The path to one file, or NA. When the same file is present in several
# formats, the first in supported_formats is used and the choice is reported.
find_data_file <- function(index, file) {
  hits <- index[[tolower(file)]]
  if (is.null(hits)) {
    return(NA_character_)
  }
  rank <- match(tolower(tools::file_ext(hits)), supported_formats)
  hits <- hits[order(rank)]
  if (length(hits) > 1) {
    message(file, ": found ", length(hits), " copies; using ", hits[[1]])
  }
  hits[[1]]
}

needs_haven <- function(ext) {
  if (!requireNamespace("haven", quietly = TRUE)) {
    stop(
      "Reading .", ext, " files needs the haven package: install.packages(\"haven\")",
      call. = FALSE
    )
  }
}

read_header <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("tab", "txt", "dat", "csv")) {
    line <- readLines(path, n = 1L, warn = FALSE)
    sep <- if (ext == "csv") "," else "\t"
    return(gsub('^"|"$', "", trimws(strsplit(line, sep, fixed = TRUE)[[1]])))
  }
  needs_haven(ext)
  if (ext == "dta") {
    return(names(haven::read_dta(path, n_max = 0)))
  }
  names(haven::read_sav(path, n_max = 0))
}

# Read only the wanted columns of one file. Names are matched ignoring case,
# because the same file can spell them differently in different formats, and
# the columns come back spelt as `wanted` spells them.
#
# Values are the codes as deposited: value labels are dropped and SPSS
# user-missing codes are kept, so every format gives the same numbers.
read_columns <- function(path, wanted) {
  ext <- tolower(tools::file_ext(path))
  header <- read_header(path)
  at <- match(tolower(wanted), tolower(header))
  found <- wanted[!is.na(at)]
  columns <- header[at[!is.na(at)]]

  if (ext %in% c("tab", "txt", "dat", "csv")) {
    classes <- ifelse(header %in% columns, NA, "NULL")
    data <- utils::read.table(
      path,
      header = TRUE, sep = if (ext == "csv") "," else "\t",
      quote = if (ext == "csv") "\"" else "", comment.char = "",
      colClasses = classes, check.names = FALSE, na.strings = c("", "NA"),
      strip.white = TRUE, stringsAsFactors = FALSE
    )
  } else if (ext == "dta") {
    data <- haven::read_dta(path, col_select = tidyselect::all_of(columns))
    data <- as.data.frame(haven::zap_labels(data))
  } else {
    data <- haven::read_sav(path, col_select = tidyselect::all_of(columns), user_na = TRUE)
    data <- as.data.frame(haven::zap_labels(data, user_na = TRUE))
  }

  names(data) <- found[match(tolower(names(data)), tolower(found))]
  list(data = data[, found, drop = FALSE], missing = setdiff(wanted, found))
}

# Trimmed and upper-cased, so the same person links across files that
# formatted the identifier differently.
normalise_identifier <- function(x) {
  toupper(trimws(as.character(x)))
}

# Replace one variable's missing-value codes with NA. `codes` is
# list(values = c(...), ranges = list(c(lo, hi), ...)); an open end is NA.
apply_missing_codes <- function(x, codes) {
  if (!is.numeric(x) || is.null(codes)) {
    return(x)
  }
  drop <- x %in% codes$values
  for (r in codes$ranges) {
    lo <- if (is.na(r[[1]])) -Inf else r[[1]]
    hi <- if (is.na(r[[2]])) Inf else r[[2]]
    drop <- drop | (!is.na(x) & x >= lo & x <= hi)
  }
  x[drop] <- NA
  x
}

# Write one table as csv, dta (Stata) or sav (SPSS). `path` has no extension.
#
# Stata and SPSS files carry each column's label and its value labels, from
# the data dictionary, so they open ready to use. CSV has nowhere to put them;
# codebook.csv lists them instead. Stata keeps variable labels to 80
# characters, so longer ones are cut there.
write_output <- function(data, path, format, labels = list(), value_labels = list()) {
  file <- paste0(path, ".", format)
  if (format == "csv") {
    utils::write.csv(data, file, row.names = FALSE, na = "")
    return(file)
  }
  if (!format %in% c("dta", "sav")) {
    stop("OUTPUT_FORMAT must be \"csv\", \"dta\" or \"sav\", not \"", format, "\".", call. = FALSE)
  }
  needs_haven(format)
  for (column in names(data)) {
    codes <- value_labels[[column]]
    if (!is.null(codes) && is.numeric(data[[column]])) {
      data[[column]] <- haven::labelled(as.double(data[[column]]), labels = codes)
    }
    label <- labels[[column]]
    if (!is.null(label)) {
      attr(data[[column]], "label") <- if (format == "dta") substr(label, 1, 80) else label
    }
  }
  if (format == "dta") haven::write_dta(data, file) else haven::write_sav(data, file)
  file
}

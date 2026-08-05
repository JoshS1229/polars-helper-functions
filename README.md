# polars-helper-functions

Reusable helper utilities for common Polars workflows, including:

- Showing unique values by column or row combinations
- Writing Polars data to Excel (raw or table mode)
- Cleaning column names into snake_case
- Cleaning/normalizing string columns
- Checking merge quality with a Stata-style merge summary
- Saving/loading Polars schemas to/from JSON for reproducible imports

## Installation

### Option A: Local editable install (best while developing)

From the repository root:

```bash
pip install -e .
```

### Option B: Standard local install

```bash
pip install .
```

## Quick usage

### Import conventions

Use the package namespace (`phf`) for **transformation** helpers, and import
**inspection** helpers directly by function name.

```python
import polars as pl
import polars_helper_functions as phf
from polars_helper_functions import check_merge, sample_lazyframe, show_unique, tab
```

This keeps call sites clear:

- `phf.clean_names(...)`, `phf.clean_strings(...)`, `phf.save_schema(...)`, etc. for transformations/workflow helpers
- `show_unique(...)`, `check_merge(...)`, `tab(...)` for inspection/diagnostics

### Example

```python
import polars as pl
import polars_helper_functions as phf
from polars_helper_functions import check_merge, show_unique, tab

lf = pl.DataFrame({"Customer ID": [1, 2, 2], "State": ["CA", "CA", "NY"]}).lazy()
show_unique(lf, ["State"])

# Clean names
cleaned = phf.clean_names(pl.DataFrame({"Customer ID": [1], "Order-Date": ["2026-01-01"]}))
print(cleaned.columns)  # ['customer_id', 'order_date']

# Clean/normalize strings
cleaned = phf.clean_strings(cleaned)

# Save/load schema directly from LazyFrame/DataFrame/schema
lf = pl.scan_csv("data/*.csv", infer_schema_length=None)
phf.save_schema(lf, "intermediate/schema.json", infer_schema_length=None)
loaded_schema = phf.load_saved_schema("intermediate/schema.json")

# Deterministic pseudo-random sample from LazyFrame
lf_base = pl.scan_parquet("data/base.parquet")
lf_base_sample = phf.sample_lazyframe(lf_base, n_rows=1_000, seed=42)

# Frequency tables are inspection helpers
df = pl.DataFrame({"state": ["CA", "CA", "NY"], "segment": ["A", "B", "A"]})
print(tab(df, ["state", "segment"]))
```

## API

### `show_unique(lf, cols, mode="column")`
Show unique values from one or more columns in a `LazyFrame`.

### `tab(df, col)`
Create one-way or multi-way frequency tables with proportions.

### `write_excel_polars(file_path, df, sheet_name, mode="raw", table_name=None)`
Write a Polars DataFrame to Excel via `openpyxl`.

### `clean_names(obj)`
Clean column names into snake_case for a list of names or a DataFrame/LazyFrame.

### `clean_strings(df, cols=None, normalize=False)`
Standardize string columns with optional aggressive normalization.

### `check_merge(left, right, on=None, left_on=None, right_on=None)`
Print merge diagnostics based on unique keys, print unmatched keys below the merge result,
and return the unmatched keys as a Polars DataFrame for full inspection when assigned to a
variable.

### `sample_lazyframe(lf, n_rows, seed=0)`
Return a deterministic pseudo-random sample from a `LazyFrame` as a `DataFrame`.

### `save_schema(schema_or_frame, schema_path, infer_schema_length=None)`
Save a schema, DataFrame, or LazyFrame to a JSON schema file.

### `load_saved_schema(schema_path)`
Load a schema JSON file and return a `dict[str, pl.DataType]` usable in Polars `schema=`.

## Development notes

- Source code uses `src/` layout.
- Packaging metadata is in `pyproject.toml`.

## License

MIT

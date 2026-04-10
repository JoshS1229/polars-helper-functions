# polars-helper-functions

Reusable helper utilities for common Polars workflows, including:

- Showing unique values by column or row combinations
- Sending dataframes/lazyframes to Spyder Variable Explorer
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
from polars_helper_functions import check_merge, show_unique, tab, view
```

This keeps call sites clear:

- `phf.clean_names(...)`, `phf.clean_strings(...)`, `phf.save_schema(...)`, etc. for transformations/workflow helpers
- `show_unique(...)`, `check_merge(...)`, `tab(...)`, `view(...)` for inspection/diagnostics

### Example

```python
import polars as pl
import polars_helper_functions as phf
from polars_helper_functions import check_merge, show_unique, tab, view

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

# Frequency table and Spyder view are inspection helpers
df = pl.DataFrame({"state": ["CA", "CA", "NY"], "segment": ["A", "B", "A"]})
print(tab(df, ["state", "segment"]))
view(df, name="my_df")
```

## API

### `show_unique(lf, cols, mode="column")`
Show unique values from one or more columns in a `LazyFrame`.

### `tab(df, col)`
Create one-way or multi-way frequency tables with proportions.

### `view(df, n=100, name="a1_VIEW_DF")`
Send a Polars DataFrame/LazyFrame to Spyder Variable Explorer by assigning it in `__main__`.

### `write_excel_polars(file_path, df, sheet_name, mode="raw", table_name=None)`
Write a Polars DataFrame to Excel via `openpyxl`.

### `clean_names(obj)`
Clean column names into snake_case for a list of names or a DataFrame/LazyFrame.

### `clean_strings(df, cols=None, normalize=False)`
Standardize string columns with optional aggressive normalization.

### `check_merge(left, right, on=None, left_on=None, right_on=None, view_unmatched=False)`
Print merge diagnostics based on unique keys and optionally send unmatched keys to Spyder.

### `sample_lazyframe(lf, n_rows, seed=0)`
Return a deterministic pseudo-random sample from a `LazyFrame` as a `DataFrame`.

### `save_schema(schema_or_frame, schema_path, infer_schema_length=None)`
Save a schema, DataFrame, or LazyFrame to a JSON schema file.

### `load_saved_schema(schema_path)`
Load a schema JSON file and return a `dict[str, pl.DataType]` usable in Polars `schema=`.

## Using this package in Spyder

1. Open **Spyder** using the same Python environment where you installed this package.
2. In Spyder, run:

   ```python
   import polars as pl
   import polars_helper_functions as phf
   from polars_helper_functions import check_merge, show_unique, tab, view
   ```

3. Use transformation helpers via `phf`, and inspection helpers directly:

   ```python
   df = pl.DataFrame({" Name ": [" Alice  ", "Bob"], "Zip-Code": [" 12345", "12345 "]})
   df = phf.clean_names(df)
   df = phf.clean_strings(df)
   view(df, name="my_clean_df")
   ```

4. Check **Variable Explorer** in Spyder for `my_clean_df`.

### If Spyder cannot import the package

Confirm Spyder is using the right interpreter:

- **Tools → Preferences → Python Interpreter**
- Select the environment/interpreter where you ran `pip install -e .`

Then restart Spyder.

## Development notes

- Source code uses `src/` layout.
- Packaging metadata is in `pyproject.toml`.

## License

MIT

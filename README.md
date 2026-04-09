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

```python
import polars as pl
from polars_helper_functions import (
    check_merge,
    clean_names,
    clean_strings,
    load_saved_schema,
    save_schema,
    show_unique,
)

lf = pl.DataFrame({"Customer ID": [1, 2, 2], "State": ["CA", "CA", "NY"]}).lazy()
show_unique(lf, ["State"])

# Clean names
cleaned = clean_names(pl.DataFrame({"Customer ID": [1], "Order-Date": ["2026-01-01"]}))
print(cleaned.columns)  # ['customer_id', 'order_date']

# Save/load schema directly from LazyFrame/DataFrame/schema
lf = pl.scan_csv("data/*.csv", infer_schema_length=None)
save_schema(lf, "intermediate/schema.json", infer_schema_length=None)
loaded_schema = load_saved_schema("intermediate/schema.json")
```

## API

### `show_unique(lf, cols, mode="column")`
Show unique values from one or more columns in a `LazyFrame`.

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
   ```

3. Use helper functions directly:

   ```python
   df = pl.DataFrame({" Name ": [" Alice  ", "Bob"], "Zip-Code": [" 12345", "12345 "]})
   df = phf.clean_names(df)
   df = phf.clean_strings(df)
   phf.view(df, name="my_clean_df")
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

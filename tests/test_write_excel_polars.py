from datetime import timedelta
from zipfile import ZipFile

import polars as pl
from openpyxl import Workbook, load_workbook

from polars_helper_functions import write_excel_polars


def test_replaces_only_target_worksheet_part(tmp_path):
    path = tmp_path / "existing.xlsx"
    workbook = Workbook()
    source = workbook.active
    source.title = "Source"
    source["A1"] = "old"
    formulas = workbook.create_sheet("Calculations")
    formulas["A1"] = "=Source!A2*2"
    workbook.save(path)

    with ZipFile(path, "a") as archive:
        archive.writestr("xl/pivotCache/pivotCacheDefinition99.xml", b"<opaque-pivot-data/>")

    with ZipFile(path) as archive:
        formula_before = archive.read("xl/worksheets/sheet2.xml")
        pivot_before = archive.read("xl/pivotCache/pivotCacheDefinition99.xml")

    write_excel_polars(path, pl.DataFrame({"value": [21]}), "Source")

    with ZipFile(path) as archive:
        assert archive.read("xl/worksheets/sheet2.xml") == formula_before
        assert archive.read("xl/pivotCache/pivotCacheDefinition99.xml") == pivot_before

    result = load_workbook(path, data_only=False)
    assert result["Source"]["A2"].value == 21
    assert result["Calculations"]["A1"].value == "=Source!A2*2"


def test_adds_sheet_and_can_write_table_to_existing_workbook(tmp_path):
    path = tmp_path / "existing.xlsx"
    Workbook().save(path)

    write_excel_polars(
        path,
        pl.DataFrame({"name": ["Alice", " Bob "]}),
        "Output",
        mode="table",
        table_name="OutputTable",
    )

    result = load_workbook(path)
    assert result["Output"]["A3"].value == " Bob "
    assert "OutputTable" in result["Output"].tables


def test_writes_timedelta_as_excel_day_fraction(tmp_path):
    path = tmp_path / "existing.xlsx"
    Workbook().save(path)

    write_excel_polars(
        path,
        pl.DataFrame({"elapsed": [timedelta(days=1, hours=12)]}),
        "Output",
    )

    result = load_workbook(path, data_only=True)
    assert result["Output"]["A2"].value == 1.5


def test_rejects_unknown_mode_before_creating_a_file(tmp_path):
    path = tmp_path / "new.xlsx"

    try:
        write_excel_polars(path, pl.DataFrame({"a": [1]}), "Output", mode="unknown")
    except ValueError as error:
        assert "mode" in str(error)
    else:
        raise AssertionError("Expected ValueError")

    assert not path.exists()

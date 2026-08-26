"""Small, surgical OOXML writer used by :func:`write_excel_polars`.

Unlike workbook object models, this module treats an ``.xlsx`` file as the ZIP
package it is.  Consequently, updating a worksheet does not deserialize and
re-serialize unrelated workbook features (notably pivot caches and array
formulas).
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from datetime import date, datetime, time, timedelta
from itertools import chain
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
_SHEET_REL = f"{_REL}/worksheet"
_TABLE_REL = f"{_REL}/table"

ET.register_namespace("", _MAIN)
ET.register_namespace("r", _REL)


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xml_cell(parent, row: int, column: int, value) -> None:
    cell = ET.SubElement(parent, f"{{{_MAIN}}}c", r=f"{_column_name(column)}{row}")
    if value is None:
        return
    if isinstance(value, bool):
        cell.set("t", "b")
        ET.SubElement(cell, f"{{{_MAIN}}}v").text = "1" if value else "0"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            cell.set("t", "e")
            ET.SubElement(cell, f"{{{_MAIN}}}v").text = "#NUM!"
        else:
            ET.SubElement(cell, f"{{{_MAIN}}}v").text = str(value)
    elif isinstance(value, timedelta):
        # Excel stores elapsed time as a number of days.  ``timedelta`` does
        # not provide ``isoformat()``, and writing its string representation
        # would prevent formulas from treating the duration as a number.
        ET.SubElement(cell, f"{{{_MAIN}}}v").text = str(
            value.total_seconds() / 86_400
        )
    elif isinstance(value, (datetime, date, time)):
        # ISO dates are understood by modern Excel and avoid mutating the
        # workbook's shared style table merely to add a date number format.
        cell.set("t", "d")
        ET.SubElement(cell, f"{{{_MAIN}}}v").text = value.isoformat()
    else:
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{{{_MAIN}}}is")
        text = ET.SubElement(inline, f"{{{_MAIN}}}t")
        string = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
        if string[:1].isspace() or string[-1:].isspace():
            text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = string


def _worksheet_xml(df, table_relationship_id: str | None = None) -> bytes:
    root = ET.Element(f"{{{_MAIN}}}worksheet")
    data = ET.SubElement(root, f"{{{_MAIN}}}sheetData")
    for row_number, values in enumerate(chain((df.columns,), df.iter_rows()), 1):
        row = ET.SubElement(data, f"{{{_MAIN}}}row", r=str(row_number))
        for column, value in enumerate(values, 1):
            _xml_cell(row, row_number, column, value)
    if table_relationship_id:
        parts = ET.SubElement(root, f"{{{_MAIN}}}tableParts", count="1")
        ET.SubElement(parts, f"{{{_MAIN}}}tablePart", {f"{{{_REL}}}id": table_relationship_id})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _resolve(source: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return str(PurePosixPath(source).parent.joinpath(target))


def _next_id(values, prefix="rId") -> str:
    used = {value for value in values if value}
    number = 1
    while f"{prefix}{number}" in used:
        number += 1
    return f"{prefix}{number}"


def _table_xml(df, table_name: str, table_id: int) -> bytes:
    if not df.width:
        raise ValueError("Excel tables require at least one column.")
    ref = f"A1:{_column_name(df.width)}{df.height + 1}"
    root = ET.Element(
        f"{{{_MAIN}}}table",
        id=str(table_id), name=table_name, displayName=table_name, ref=ref,
    )
    ET.SubElement(root, f"{{{_MAIN}}}autoFilter", ref=ref)
    columns = ET.SubElement(root, f"{{{_MAIN}}}tableColumns", count=str(df.width))
    for number, name in enumerate(df.columns, 1):
        ET.SubElement(columns, f"{{{_MAIN}}}tableColumn", id=str(number), name=str(name))
    ET.SubElement(
        root, f"{{{_MAIN}}}tableStyleInfo", name="TableStyleMedium2",
        showFirstColumn="0", showLastColumn="0", showRowStripes="1", showColumnStripes="0",
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def update_xlsx_sheet(file_path: Path, df, sheet_name: str, mode: str, table_name: str | None) -> None:
    """Replace one worksheet part while copying every other ZIP part unchanged."""
    replacements: dict[str, bytes | None] = {}
    with ZipFile(file_path, "r") as source:
        workbook = ET.fromstring(source.read("xl/workbook.xml"))
        workbook_rels = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        relationships = {r.get("Id"): r for r in workbook_rels}
        sheets = workbook.find(f"{{{_MAIN}}}sheets")
        sheet = next((s for s in sheets if s.get("name") == sheet_name), None)

        if sheet is None:
            rel_id = _next_id(relationships)
            sheet_numbers = [int(m.group(1)) for n in source.namelist() if (m := re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", n))]
            sheet_path = f"xl/worksheets/sheet{max(sheet_numbers, default=0) + 1}.xml"
            sheet_ids = [int(s.get("sheetId")) for s in sheets]
            sheet = ET.SubElement(sheets, f"{{{_MAIN}}}sheet", name=sheet_name, sheetId=str(max(sheet_ids, default=0) + 1), **{f"{{{_REL}}}id": rel_id})
            ET.SubElement(workbook_rels, f"{{{_PKG_REL}}}Relationship", Id=rel_id, Type=_SHEET_REL, Target=sheet_path.removeprefix("xl/"))
            replacements["xl/workbook.xml"] = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
            replacements["xl/_rels/workbook.xml.rels"] = ET.tostring(workbook_rels, encoding="utf-8", xml_declaration=True)
            content_types = ET.fromstring(source.read("[Content_Types].xml"))
            ET.SubElement(content_types, f"{{{_CONTENT}}}Override", PartName=f"/{sheet_path}", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
            replacements["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
        else:
            relation = relationships[sheet.get(f"{{{_REL}}}id")]
            sheet_path = _resolve("xl/workbook.xml", relation.get("Target"))

        table_rel_id = None
        if mode == "table":
            table_name = table_name or f"tbl_{sheet_name.replace(' ', '_')}"
            table_numbers = [int(m.group(1)) for n in source.namelist() if (m := re.fullmatch(r"xl/tables/table(\d+)\.xml", n))]
            table_number = max(table_numbers, default=0) + 1
            table_path = f"xl/tables/table{table_number}.xml"
            rels_path = str(PurePosixPath(sheet_path).parent / "_rels" / f"{PurePosixPath(sheet_path).name}.rels")
            rels = ET.Element(f"{{{_PKG_REL}}}Relationships")
            table_rel_id = "rId1"
            ET.SubElement(rels, f"{{{_PKG_REL}}}Relationship", Id=table_rel_id, Type=_TABLE_REL, Target=f"../tables/table{table_number}.xml")
            replacements[rels_path] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
            replacements[table_path] = _table_xml(df, table_name, table_number)
            content_types = ET.fromstring(replacements.get("[Content_Types].xml") or source.read("[Content_Types].xml"))
            ET.SubElement(content_types, f"{{{_CONTENT}}}Override", PartName=f"/{table_path}", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml")
            replacements["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)

        replacements[sheet_path] = _worksheet_xml(df, table_rel_id)
        fd, temporary = tempfile.mkstemp(dir=file_path.parent, suffix=".xlsx")
        os.close(fd)
        try:
            with ZipFile(temporary, "w", ZIP_DEFLATED) as destination:
                for item in source.infolist():
                    if item.filename not in replacements:
                        destination.writestr(item, source.read(item.filename))
                    elif replacements[item.filename] is not None:
                        destination.writestr(item, replacements.pop(item.filename))
                for name, contents in replacements.items():
                    if contents is not None:
                        destination.writestr(name, contents)
            # Close the source before atomically replacing it.  This matters
            # on Windows, where replacing an open file can fail.
            source.close()
            os.replace(temporary, file_path)
        finally:
            Path(temporary).unlink(missing_ok=True)

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
import time as _time
from datetime import date, datetime, time, timedelta
from itertools import chain
from pathlib import Path, PurePosixPath
from xml.dom import minidom
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
_SHEET_REL = f"{_REL}/worksheet"
_TABLE_REL = f"{_REL}/table"
_STYLES_REL = f"{_REL}/styles"

ET.register_namespace("", _MAIN)
ET.register_namespace("r", _REL)


def _temporal_formats(df) -> dict[int, str]:
    """Use declared column types, including columns containing only nulls."""
    import polars as pl

    for name, dtype in df.schema.items():
        if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
            raise ValueError(
                f"Excel does not support time zones: column {name!r}. "
                "Convert to the desired time zone and remove the time zone before export."
            )

    return {
        index: "yyyy-mm-dd" if dtype == pl.Date else "yyyy-mm-dd hh:mm:ss"
        for index, dtype in enumerate(df.schema.values(), 1)
        if dtype == pl.Date or isinstance(dtype, pl.Datetime)
    }


def _date_styles(styles_xml: bytes, formats) -> tuple[bytes, dict[str, int]]:
    # DOM retains namespace prefixes and extension declarations in existing
    # styles, including those referenced by mc:Ignorable attributes.
    document = minidom.parseString(styles_xml)
    root = document.documentElement

    def children(node, name):
        return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE
                and c.namespaceURI == _MAIN and c.localName == name]

    def element(name, **attributes):
        qualified = f"{root.prefix}:{name}" if root.prefix else name
        node = document.createElementNS(_MAIN, qualified)
        for key, value in attributes.items():
            node.setAttribute(key, str(value))
        return node

    num_fmts = next(iter(children(root, "numFmts")), None)
    if num_fmts is None:
        num_fmts = element("numFmts", count=0)
        root.insertBefore(num_fmts, root.firstChild)
    cell_xfs = next(iter(children(root, "cellXfs")), None)
    if cell_xfs is None:
        cell_xfs = element("cellXfs", count=1)
        cell_xfs.appendChild(element("xf", numFmtId=0))
        following = next((c for c in root.childNodes
                          if c.nodeType == c.ELEMENT_NODE and c.localName in
                          {"cellStyles", "dxfs", "tableStyles", "colors", "extLst"}), None)
        root.insertBefore(cell_xfs, following)

    from openpyxl.styles.numbers import BUILTIN_FORMATS

    known = dict(BUILTIN_FORMATS)
    known.update({int(n.getAttribute("numFmtId")): n.getAttribute("formatCode")
                  for n in children(num_fmts, "numFmt")})
    result = {}
    for code in dict.fromkeys(formats):
        number = next((i for i, fmt in known.items() if fmt == code), None)
        if number is None:
            number = max(163, *known) + 1
            num_fmts.appendChild(element("numFmt", numFmtId=number, formatCode=code))
            known[number] = code
        xfs = children(cell_xfs, "xf")
        index = next((i for i, xf in enumerate(xfs)
                      if xf.getAttribute("numFmtId") == str(number)
                      and xf.getAttribute("applyNumberFormat") != "0"
                      and set(xf.attributes.keys()) <= {"numFmtId", "applyNumberFormat"}
                      and not xf.hasChildNodes()), None)
        if index is None:
            index = len(xfs)
            cell_xfs.appendChild(element("xf", numFmtId=number, applyNumberFormat=1))
        result[code] = index
    num_fmts.setAttribute("count", str(len(children(num_fmts, "numFmt"))))
    cell_xfs.setAttribute("count", str(len(children(cell_xfs, "xf"))))
    return document.toxml(encoding="utf-8"), result


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
        # ISO date cells preserve the value independently of the workbook's
        # 1900/1904 epoch. The worksheet writer assigns their display styles.
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


def _worksheet_xml(df, table_relationship_id: str | None = None, column_styles=None) -> bytes:
    root = ET.Element(f"{{{_MAIN}}}worksheet")
    data = ET.SubElement(root, f"{{{_MAIN}}}sheetData")
    for row_number, values in enumerate(chain((df.columns,), df.iter_rows()), 1):
        row = ET.SubElement(data, f"{{{_MAIN}}}row", r=str(row_number))
        for column, value in enumerate(values, 1):
            _xml_cell(row, row_number, column, value)
            if row_number > 1 and column_styles and column in column_styles:
                row[-1].set("s", str(column_styles[column]))
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


def _replace_workbook(temporary: str, file_path: Path) -> None:
    """Allow brief Windows/network-share locks to clear without rewriting data."""
    for attempt in range(6):
        try:
            os.replace(temporary, file_path)
            return
        except PermissionError as error:
            if attempt == 5:
                raise PermissionError(
                    error.errno,
                    f"Cannot replace Excel workbook after 6 attempts. Close the "
                    f"workbook in Excel and check write/delete permissions on the "
                    f"file and its folder. The existing workbook was not replaced.",
                    str(file_path),
                ) from error
            _time.sleep(0.1 * 2 ** attempt)


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

        column_formats = _temporal_formats(df)
        column_styles = {}
        if column_formats:
            style_relation = next((r for r in workbook_rels if r.get("Type") == _STYLES_REL), None)
            if style_relation is None:
                styles_path = "xl/styles.xml"
                ET.SubElement(workbook_rels, f"{{{_PKG_REL}}}Relationship",
                              Id=_next_id(r.get("Id") for r in workbook_rels),
                              Type=_STYLES_REL, Target="styles.xml")
                replacements["xl/_rels/workbook.xml.rels"] = ET.tostring(workbook_rels, encoding="utf-8", xml_declaration=True)
                content_types = ET.fromstring(replacements.get("[Content_Types].xml") or source.read("[Content_Types].xml"))
                ET.SubElement(content_types, f"{{{_CONTENT}}}Override", PartName=f"/{styles_path}",
                              ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")
                replacements["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
                # A styles part is optional. Create Excel's normal base styles
                # before adding date formats, without loading the workbook.
                from openpyxl import Workbook
                from openpyxl.styles.stylesheet import write_stylesheet
                from openpyxl.xml.functions import tostring

                styles_xml = tostring(write_stylesheet(Workbook()))
            else:
                styles_path = _resolve("xl/workbook.xml", style_relation.get("Target"))
                styles_xml = source.read(styles_path)
            replacements[styles_path], style_ids = _date_styles(styles_xml, column_formats.values())
            column_styles = {column: style_ids[code] for column, code in column_formats.items()}

        replacements[sheet_path] = _worksheet_xml(df, table_rel_id, column_styles)
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
            _replace_workbook(temporary, file_path)
        finally:
            Path(temporary).unlink(missing_ok=True)

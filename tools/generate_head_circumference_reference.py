"""Convert the WHO expanded XLSX tables into Baby Buddy's daily LMS CSV format.

Input files are the official `hcfa-*-zscore-expanded-tables.xlsx` downloads.
This helper uses only the Python standard library so reference data can be
regenerated without adding a runtime dependency.
"""

import csv
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def shared_strings(source):
    root = ET.fromstring(source.read("xl/sharedStrings.xml"))
    return ["".join(item.itertext()) for item in root.findall(f"{NS}si")]


def rows(source):
    strings = shared_strings(source)
    sheet = ET.fromstring(source.read("xl/worksheets/sheet1.xml"))
    for row in sheet.findall(f".//{NS}row"):
        values = []
        for cell in row.findall(f"{NS}c"):
            value = cell.findtext(f"{NS}v", default="")
            if cell.get("t") == "s":
                value = strings[int(value)]
            values.append(value)
        yield values


def convert(source_path, destination_path):
    with zipfile.ZipFile(source_path) as source:
        source_rows = list(rows(source))

    header_index = next(
        index
        for index, row in enumerate(source_rows)
        if row[:4] == ["Day", "L", "M", "S"]
    )
    data = source_rows[header_index + 1 :]
    with destination_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(["Day", "L", "M", "S"])
        for row in data:
            if len(row) < 4 or not row[0].isdigit():
                continue
            writer.writerow(row[:4])


if __name__ == "__main__":
    input_directory = Path(sys.argv[1])
    output_directory = Path(sys.argv[2])
    for sex in ("girls", "boys"):
        convert(
            input_directory / f"{sex}.xlsx",
            output_directory / f"head_circumference_percentile_{sex}.csv",
        )

"""Tables (linking table, metadata overview) that open correctly in spreadsheet applications."""

import re
import zipfile

import pandas as pd
import pytest

from dicom_pseudo.core.tables import read_table, write_table


@pytest.fixture
def table():
    return pd.DataFrame({'Description': ['= NONE =', '+plus', '-minus', '@at', 'normal', '-1.5', 'accentué'],
                         'Number': ['1', '2', '3', '4', '5', '6', '7']})


def test_xlsx_has_no_formulas(table, tmp_path):
    path = str(tmp_path / 't.xlsx')
    write_table(table, path)
    sheet = zipfile.ZipFile(path).read('xl/worksheets/sheet1.xml').decode()
    assert '<f>' not in sheet
    assert read_table(path, dtype=str).equals(table)


def test_csv_escapes_formulas(table, tmp_path):
    path = str(tmp_path / 't.csv')
    write_table(table, path)
    raw = open(path, 'rb').read()
    assert raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig')
    assert "'= NONE =" in text and "'@at" in text and "'-minus" in text and "'-1.5" not in text
    assert read_table(path, dtype=str).equals(table)


def test_xlsx_illegal_and_long_values(tmp_path):
    path = str(tmp_path / 't.xlsx')
    write_table(pd.DataFrame({'Value': ['binary\x00\x01data', 'x' * 40000]}), path)
    values = read_table(path, dtype=str)['Value'].tolist()
    assert values[0] == 'binarydata'
    assert len(values[1]) == 32767 and values[1].endswith('...')

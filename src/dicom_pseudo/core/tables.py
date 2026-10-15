"""
Reading and writing of the tables (linking table, metadata overview) as .xlsx or .csv files that open correctly in
spreadsheet applications such as Microsoft Excel:
    - .xlsx: text is always stored as text, never as a formula (e.g. a SeriesDescription '= NONE =' would otherwise be
      written as an invalid formula, and the file reported as damaged)
    - .csv: UTF-8 with byte order mark (so that non-ASCII characters are recognised), and text starting with a formula
      character (=, +, -, @) prefixed with an apostrophe so that it is not evaluated as a formula (prefix removed again
      when the table is read by this tool)
"""

""" IMPORTS """

# Pre-installed packages
import os
import re

# Pandas
import pandas as pd

# Openpyxl
from openpyxl import Workbook


""" DEFINITIONS """

# First characters for which spreadsheet applications evaluate text as a formula
FORMULA_CHARACTERS = ('=', '+', '-', '@')

# Numbers (not escaped, e.g. negative values)
NUMBER = re.compile(r'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$')


""" FUNCTIONS """

def _is_formula_like(value) -> bool:
    """
    Check whether a value would be evaluated as a formula by a spreadsheet application.
    """

    return isinstance(value, str) and value.startswith(FORMULA_CHARACTERS) and not NUMBER.match(value)

def _write_xlsx(df: pd.DataFrame, path: str) -> None:
    """
    Write a table as .xlsx, with text always stored as text (never as a formula).
    """

    workbook = Workbook()
    sheet = workbook.active
    sheet.append([str(column) for column in df.columns])
    for row in df.itertuples(index=False):
        sheet.append([None if pd.isna(value) else value for value in row])
    for row in sheet.iter_rows(min_row=1):
        for cell in row:
            if _is_formula_like(cell.value):
                cell.data_type = 's'
    sheet.freeze_panes = 'A2'
    workbook.save(path)

def write_table(df: pd.DataFrame, path: str) -> None:
    """
    Write a table as .xlsx or .csv (according to the file extension), safe to open in spreadsheet applications.

    Inputs:
        - df: pd.DataFrame = table
        - path: str = path to table (.xlsx or .csv), folders are created if needed
    """

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if path.lower().endswith('.csv'):
        escaped = df.map(lambda value: "'" + value if _is_formula_like(value) else value)
        escaped.to_csv(path, index=False, encoding='utf-8-sig')
    else:
        _write_xlsx(df, path)

def read_table(path: str, dtype=None) -> pd.DataFrame:
    """
    Read a table written by write_table (.xlsx or .csv).

    Inputs:
        - path: str = path to table (.xlsx or .csv)
        - dtype = data type of the columns (default = None => inferred)

    Outputs:
        - df: pd.DataFrame = table
    """

    if path.lower().endswith('.csv'):
        df = pd.read_csv(path, dtype=dtype, encoding='utf-8-sig')
        return df.map(lambda value: value[1:] if isinstance(value, str) and value.startswith("'") and _is_formula_like(value[1:]) else value)
    return pd.read_excel(path, dtype=dtype)

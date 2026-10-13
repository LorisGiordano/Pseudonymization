""" IMPORTS """

# Pre-installed packages
import os

# Pandas
import pandas as pd


""" FUNCTIONS """

def save_link_table(link_table: str, series_records: dict, identifier: str) -> None:
    """
    Save the linking table (one row per DICOM series), merged with the existing linking table if any.

    Inputs:
        - link_table: str = path to linking table (.xlsx or .csv)
        - series_records: dict = linking table records, one per series
        - identifier: str = DICOM keyword used as identifier
    """

    if not series_records:
        return

    is_csv = link_table.lower().endswith('.csv')
    df = pd.DataFrame(list(series_records.values())).astype(str)

    # merge with existing linking table, newer rows replace older rows of the same series
    if os.path.exists(link_table):
        existing = pd.read_csv(link_table, dtype=str) if is_csv else pd.read_excel(link_table, dtype=str)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=[f'Original {identifier}', 'Original SeriesInstanceUID', 'Output folder'], keep='last')

    os.makedirs(os.path.dirname(os.path.abspath(link_table)), exist_ok=True)
    if is_csv:
        df.to_csv(link_table, index=False)
    else:
        df.to_excel(link_table, index=False)

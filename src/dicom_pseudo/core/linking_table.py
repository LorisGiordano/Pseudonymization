"""
Linking table between original and pseudonymized identifiers, one row per DICOM series (and input/output folder).
The linking table allows to re-identify the data and must be stored separately from the pseudonymized data.
"""

""" IMPORTS """

# Pre-installed packages
import os

# Pandas
import pandas as pd

# Pydicom
import pydicom

# Core modules
from .identity import SeriesIdentity


""" DEFINITIONS """

# Series information stored in the linking table (read from the original DICOM)
SERIES_INFORMATION = ('Modality', 'SeriesNumber', 'SeriesDescription', 'BurnedInAnnotation')


""" FUNCTIONS """

def link_record(identity: SeriesIdentity, dicom_data: pydicom.dataset.Dataset, input_folder: str) -> dict:
    """
    Create the linking table record of a series.

    Inputs:
        - identity: SeriesIdentity = identity of the series
        - dicom_data: pydicom.dataset.Dataset = original dicom file object of the series
        - input_folder: str = relative input folder(s) of the series

    Outputs:
        - record: dict = linking table record (number of files still 0)
    """

    identifier = identity.identifier
    return {
        f'Original {identifier}': identity.original_id,
        f'Pseudonym {identifier}': identity.pseudo_id,
        f'Patient pseudonym {identifier}': identity.patient_pseudo_id,
        'Linkage': identity.linkage,
        'Original StudyInstanceUID': identity.original_study_uid,
        'Original SeriesInstanceUID': identity.original_series_uid,
        'Pseudonymized StudyInstanceUID': identity.pseudo_study_uid,
        'Pseudonymized SeriesInstanceUID': identity.pseudo_series_uid,
        **{keyword: str(dicom_data.get(keyword, '')) for keyword in SERIES_INFORMATION},
        'Output folder': identity.output_folder,
        'Input folder': input_folder,
        'Number of files': 0,
    }

def add_record(series_records: dict, record: dict, identifier: str, number_of_files: int = 1) -> None:
    """
    Add a record to the linking table records: one record per series and input/output folder, counting its files.

    Inputs:
        - series_records: dict = linking table records, updated in place
        - record: dict = linking table record (see link_record)
        - identifier: str = DICOM keyword used as identifier
        - number_of_files: int = number of files of the record to add (default = 1)
    """

    record_key = (record[f'Original {identifier}'], record['Original SeriesInstanceUID'], record['Input folder'], record['Output folder'])
    if record_key not in series_records:
        series_records[record_key] = record
    series_records[record_key]['Number of files'] += number_of_files

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
        subset = [column for column in (f'Original {identifier}', 'Original SeriesInstanceUID', 'Input folder', 'Output folder') if column in df.columns]
        df = df.drop_duplicates(subset=subset, keep='last')

    os.makedirs(os.path.dirname(os.path.abspath(link_table)), exist_ok=True)
    if is_csv:
        df.to_csv(link_table, index=False)
    else:
        df.to_excel(link_table, index=False)

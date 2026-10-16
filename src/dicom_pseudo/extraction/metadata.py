"""
Metadata of the profile stored with the extracted images (metadata.json per series, metadata.xlsx overview).
"""

""" IMPORTS """

# Pre-installed packages
import os
import json

# Pandas
import pandas as pd

# Pydicom
import pydicom
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence

# Core modules
from ..core.settings import FIELDS_TO_KEEP, select_profile
from ..core.tables import read_table, write_table


""" FUNCTIONS """

def profile_fields(profile: int) -> dict:
    """
    Get the fields of a profile stored as metadata: the fields kept by the profile, on top of the fields kept in all
    cases (which describe the image itself and are stored in the NifTi, or are pseudonymized identifiers).

    Inputs:
        - profile: int = number corresponding to profile to be selected

    Outputs:
        - fields: dict = dictionary of DICOM keywords (keys) and their tags (values)
    """

    fields_to_keep, _ = select_profile(profile)
    return {keyword: tag for keyword, tag in fields_to_keep.items() if keyword not in FIELDS_TO_KEEP}

def json_value(value):
    """
    Convert a DICOM value to a JSON serializable value.
    """

    if isinstance(value, Sequence):
        return [{elem.keyword or str(elem.tag): json_value(elem.value) for elem in item} for item in value]
    if isinstance(value, (list, tuple, MultiValue)):
        return [json_value(item) for item in value]
    if isinstance(value, (int, float, str)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    try:
        return float(value) if '.' in str(value) else int(value)
    except (TypeError, ValueError):
        return str(value)

def get_metadata(dicom_data: pydicom.dataset.Dataset, fields: dict) -> dict:
    """
    Get the metadata of a DICOM dataset.

    Inputs:
        - dicom_data: pydicom.dataset.Dataset = dicom file object
        - fields: dict = dictionary of DICOM keywords (keys) and their tags (values) (see profile_fields)

    Outputs:
        - metadata: dict = metadata (JSON serializable)
    """

    # binary values (e.g. vendor private headers) are not readable metadata: only their size is written
    return {keyword: f'<binary, {len(dicom_data[tag].value or b"")} bytes>' if dicom_data[tag].VR in ('OB', 'OW', 'UN') else json_value(dicom_data[tag].value)
            for keyword, tag in fields.items() if tag in dicom_data}

def write_metadata(metadata: dict, output_directory: str) -> None:
    """
    Write the metadata of a series in metadata.json, together with its images.
    """

    with open(os.path.join(output_directory, 'metadata.json'), 'w') as file:
        json.dump(metadata, file, indent=4)

def save_metadata_table(metadata_table: str, rows: list[dict]) -> None:
    """
    Save the overview table of the extracted series (folder, NifTi information and profile fields), merged with the
    existing table if any.

    Inputs:
        - metadata_table: str = path to metadata table (.xlsx)
        - rows: list[dict] = one row per series (with 'Folder')
    """

    if not rows:
        return
    rows = [{key: json.dumps(value) if isinstance(value, (list, dict)) else value for key, value in row.items()} for row in rows]
    df = pd.DataFrame(rows)
    if os.path.exists(metadata_table):
        df = pd.concat([read_table(metadata_table), df], ignore_index=True).drop_duplicates(subset=['Folder'], keep='last')
    write_table(df, metadata_table)

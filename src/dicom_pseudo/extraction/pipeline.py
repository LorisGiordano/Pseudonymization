"""
Extraction of pseudonymized NifTi images and metadata: one output folder per DICOM series.
"""

""" IMPORTS """

# Pre-installed packages
import os
from collections import Counter

# Tqdm [optional]
try:
    from tqdm import tqdm
    PROGRESS_BAR = True
except:
    print("INFO: Progress bar not available because tqdm is not installed.")
    PROGRESS_BAR = False

# Core modules (same identifiers, pseudonyms, UIDs, output structure and linking table as the pseudonymization)
from ..core.settings import IDENTIFIERS, LINKAGES
from ..core.pseudonym import load_key
from ..core.identity import identify
from ..core.files import find_dicom_files, group_by_series
from ..core.paths import check_paths
from ..core.linking_table import link_record, add_record, save_link_table
from ..core.report import report

# Extraction modules
from .timepoints import TIME_STAMP_FIELDS
from .nifti import write_nifti
from .metadata import profile_fields, get_metadata, write_metadata, save_metadata_table


""" FUNCTIONS """

def extract_series(files: list, input_folder: str, output_root: str, identifier: str, key: bytes, fields: dict, four_d: bool = False, time_stamp: str = None, linkage: str = 'patient') -> tuple[dict, dict]:
    """
    Extract the image(s) and metadata of one series to its pseudonymized output folder (same structure as the
    pseudonymized DICOM files): <pseudonym[:16]>/<StudyInstanceUID>/<SeriesInstanceUID>, containing
        - the NifTi image(s) (see nifti.write_nifti)
        - metadata.json (fields of the profile)

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - input_folder: str = relative input folder(s) of the series (stored in the linking table)
        - output_root: str = path to output folder
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - fields: dict = fields of the profile stored as metadata (see metadata.profile_fields)
        - four_d: bool = whether to reconstruct 4D data (default = False)
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)
        - linkage: str = 'patient' or 'study' level pseudonyms (default = 'patient')

    Outputs:
        - record: dict = linking table record of the series (None if identifier missing)
        - metadata: dict = metadata of the series (None if identifier missing)
    """

    # identity of the series and its linking table record (from the original data)
    dicom_data = files[0][1]
    identity = identify(dicom_data, identifier, key, linkage)
    if identity is None:
        return None, None
    record = link_record(identity, dicom_data, input_folder)
    output_directory = os.path.join(output_root, identity.output_folder)
    os.makedirs(output_directory, exist_ok=True)

    # images and metadata
    record.update(write_nifti(files, output_directory, four_d, time_stamp))
    metadata = get_metadata(dicom_data, fields)
    write_metadata(metadata, output_directory)

    return record, metadata

def extraction(input_root: str, output_root: str, profile: int, identifier: str, time_stamp: str = None, progress_bar: bool = PROGRESS_BAR, key_file: str = None, link_table: str = None, linkage: str = 'patient') -> None:
    """
    Main function to extract pseudonymized NifTi files and metadata from a DICOM directory (or a single DICOM file).

    Inputs:
        - input_root: str = path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = path to output folder
        - profile: int = number corresponding to profile to be selected (profile 3 = 4D)
        - identifier: str = DICOM keyword to be used as identifier
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)
        - progress_bar: bool = (default = PROGRESS_BAR)
        - key_file: str = path to file containing the secret pseudonymization key, created if it does not exist
                          (default = None => key read from environment variable KEY_ENV_VARIABLE)
        - link_table: str = path to the linking table (.xlsx or .csv), outside the output folder
        - linkage: str = 'patient' or 'study' level pseudonyms (default = 'patient')
    """

    # check inputs and locations before doing anything, load the key
    if identifier not in IDENTIFIERS:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(IDENTIFIERS)})")
    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")
    if time_stamp is not None and time_stamp not in TIME_STAMP_FIELDS:
        raise SystemExit(f"Keyword '{time_stamp}' cannot be used as a time stamp keyword. (Use one of: {', '.join(TIME_STAMP_FIELDS)})")
    input_folder, single_file = check_paths(input_root, output_root, link_table, key_file)
    key = load_key(key_file)
    fields = profile_fields(profile)
    os.makedirs(output_root, exist_ok=True)

    # DICOM files (detected by content), grouped by series
    series = group_by_series(find_dicom_files(input_folder, single_file))
    print(f"Extraction of {len(series)} series ({sum(len(files) for files in series.values())} DICOM files)...")

    # extract all series (linking table always saved, also if an error occurs)
    series_records, metadata_rows, skipped, failed = {}, [], [], []
    try:
        for files in (tqdm(series.values()) if progress_bar else series.values()):
            series_folder = ';'.join(sorted({os.path.relpath(os.path.dirname(path), input_folder) for path, _ in files}))
            try:
                record, metadata = extract_series(files, series_folder, output_root, identifier, key, fields, profile == 3, time_stamp, linkage)
            except Exception as error:
                failed.append((series_folder, f'{type(error).__name__}: {error}'))
                continue
            if record is None:
                skipped.append(series_folder)
                continue
            add_record(series_records, record, identifier, len(files))
            metadata_rows.append({'Pseudonym': record[f'Pseudonym {identifier}'], 'Output folder': record['Output folder'],
                                  'Modality': record['Modality'], 'Time points': record['Time points'], **metadata})
    finally:
        save_link_table(link_table, series_records, identifier)
        save_metadata_table(os.path.join(output_root, 'metadata.xlsx'), metadata_rows)

    # report
    image_types = Counter(record['NIfTI'] for record in series_records.values())
    summary = f"{len(series_records)} series extracted ({', '.join(f'{number} {image_type}' for image_type, number in sorted(image_types.items()))})."
    report(series_records, skipped, failed, identifier, summary, 'Extraction', output_root, link_table)

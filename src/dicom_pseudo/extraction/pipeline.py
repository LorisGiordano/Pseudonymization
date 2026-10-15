"""
Extraction of NifTi images and metadata from DICOM files, reproducing the structure of the input folder.

The extraction does not pseudonymize: it is meant to be applied to pseudonymized DICOM files (see
dicom_pseudo.pseudonymization), whose folder structure is then kept. Applied to original DICOM files, the folder names
and the metadata of the profile are copied as they are.
"""

""" IMPORTS """

# Pre-installed packages
import os
import re
from collections import Counter, defaultdict

# Tqdm [optional]
try:
    from tqdm import tqdm
    PROGRESS_BAR = True
except:
    print("INFO: Progress bar not available because tqdm is not installed.")
    PROGRESS_BAR = False

# Core modules
from ..core.files import find_dicom_files, group_by_series
from ..core.paths import check_input_output
from ..core.report import report

# Extraction modules
from .timepoints import TIME_STAMP_FIELDS
from .nifti import write_nifti
from .metadata import profile_fields, get_metadata, write_metadata, save_metadata_table


""" FUNCTIONS """

def _folder_name(text: str) -> str:
    """
    Replace the characters that are not safe in folder names.
    """

    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_') or 'series'

def series_subfolders(series: dict) -> dict:
    """
    Get the subfolder of each series of an input folder: none if the folder contains a single series, otherwise
    <SeriesNumber>_<Modality> (with _<SeriesInstanceUID> if the series number is missing or the name is not unique).

    Inputs:
        - series: dict = SeriesInstanceUID (keys) and list of (path, dataset) (values) of an input folder

    Outputs:
        - subfolders: dict = SeriesInstanceUID (keys) and relative subfolder ('' for a single series) (values)
    """

    if len(series) == 1:
        return {series_uid: '' for series_uid in series}

    names = {}
    for series_uid, files in series.items():
        dicom_data = files[0][1]
        series_number = str(dicom_data.get('SeriesNumber', '') or '').strip()
        names[series_uid] = _folder_name(f"{series_number}_{dicom_data.get('Modality', '')}") if series_number else ''
    counts = Counter(names.values())
    return {series_uid: name if name and counts[name] == 1 else _folder_name(f'{name}_{series_uid}' if name else series_uid)
            for series_uid, name in names.items()}

def group_by_folder_and_series(dicom_files: list[str], input_folder: str) -> dict:
    """
    Group DICOM files by input folder and series (a series split over several folders is extracted in each folder).

    Inputs:
        - dicom_files: list[str] = paths to the DICOM files
        - input_folder: str = path to input folder

    Outputs:
        - series: dict = (relative output folder) (keys) and list of (path, dataset) sorted by InstanceNumber (values)
    """

    files_per_folder = defaultdict(list)
    for path in dicom_files:
        files_per_folder[os.path.relpath(os.path.dirname(path), input_folder)].append(path)

    series = {}
    for folder, paths in sorted(files_per_folder.items()):
        folder_series = group_by_series(paths)
        for series_uid, subfolder in series_subfolders(folder_series).items():
            series[os.path.normpath(os.path.join(folder, subfolder))] = folder_series[series_uid]
    return series

def extract_series(files: list, output_directory: str, fields: dict, four_d: bool = False, time_stamp: str = None) -> dict:
    """
    Extract the image(s) and metadata of one series:
        - the NifTi image(s) (see nifti.write_nifti)
        - metadata.json (fields of the profile)

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - output_directory: str = path to output folder of the series
        - fields: dict = fields of the profile stored as metadata (see metadata.profile_fields)
        - four_d: bool = whether to reconstruct 4D data (default = False)
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)

    Outputs:
        - overview: dict = overview of the series (NifTi information and metadata)
    """

    dicom_data = files[0][1]
    os.makedirs(output_directory, exist_ok=True)
    information = write_nifti(files, output_directory, four_d, time_stamp)
    metadata = get_metadata(dicom_data, fields)
    write_metadata(metadata, output_directory)

    return {
        **{keyword: str(dicom_data.get(keyword, '')) for keyword in ('Modality', 'SeriesNumber', 'SeriesDescription')},
        'Number of files': len(files),
        **information,
        **metadata,
    }

def extraction(input_root: str, output_root: str, profile: int = 1, time_stamp: str = None, progress_bar: bool = PROGRESS_BAR) -> None:
    """
    Main function to extract NifTi files and metadata from a DICOM directory (or a single DICOM file), reproducing the
    structure of the input folder.

    Inputs:
        - input_root: str = path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = path to output folder
        - profile: int = number corresponding to profile to be selected: fields stored as metadata, 4D reconstruction
                         for profile 3 (default = 1)
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)
        - progress_bar: bool = (default = PROGRESS_BAR)
    """

    # check inputs and locations before doing anything
    if time_stamp is not None and time_stamp not in TIME_STAMP_FIELDS:
        raise SystemExit(f"Keyword '{time_stamp}' cannot be used as a time stamp keyword. (Use one of: {', '.join(TIME_STAMP_FIELDS)})")
    input_folder, single_file = check_input_output(input_root, output_root)
    fields = profile_fields(profile)
    os.makedirs(output_root, exist_ok=True)

    # DICOM files (detected by content), grouped by input folder and series
    dicom_files = find_dicom_files(input_folder, single_file)
    series = group_by_folder_and_series(dicom_files, input_folder)
    print(f"Extraction of {len(series)} series ({len(dicom_files)} DICOM files)...")

    # extract all series (overview always saved, also if an error occurs)
    overview, failed = [], []
    try:
        for folder, files in (tqdm(series.items()) if progress_bar else series.items()):
            try:
                row = extract_series(files, os.path.join(output_root, folder), fields, profile == 3, time_stamp)
            except Exception as error:
                failed.append((folder, f'{type(error).__name__}: {error}'))
                continue
            overview.append({'Folder': folder, **row})
    finally:
        save_metadata_table(os.path.join(output_root, 'metadata.xlsx'), overview)

    # report
    image_types = Counter(row['NIfTI'] for row in overview)
    summary = f"{len(overview)} series extracted ({', '.join(f'{number} {image_type}' for image_type, number in sorted(image_types.items()))})."
    report({}, [], failed, '', summary, 'Extraction', output_root)

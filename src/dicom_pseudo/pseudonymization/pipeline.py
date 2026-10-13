""" IMPORTS """

# Pre-installed packages
import os

# Tqdm [optional]
try:
    from tqdm import tqdm
    PROGRESS_BAR = True
except:
    print("INFO: Progress bar not available because tqdm is not installed.")
    PROGRESS_BAR = False

# Pydicom
import pydicom
from pydicom.tag import Tag

# Pseudonymization modules
from .settings import IDENTIFIERS, TOOL_VERSION, select_profile
from .pseudonym import load_key, apply_pseudonym, remap_uids
from .sanitization import remove_private_tags, sanitize_dataset, ensure_file_meta
from .linking_table import save_link_table


""" FUNCTIONS """

def _is_inside(path: str, folder: str) -> bool:
    """
    Check whether a path is located inside a folder (or is the folder itself).
    """

    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([path, folder]) == folder

def _save_dicom(dicom_data: pydicom.dataset.FileDataset, output_path: str) -> None:
    """
    Save a DICOM file in standard DICOM file format (preamble, prefix and file meta information).
    """

    if int(pydicom.__version__.split('.')[0]) >= 3:
        dicom_data.save_as(output_path, enforce_file_format=True)
    else:
        dicom_data.save_as(output_path, write_like_original=False)

def pseudonymize_dicom(input_path: str, output_path: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set) -> dict:
    """
    Pseudonymize a single DICOM file.

    Inputs:
        - input_path: str = absolute path to .dcm file
        - output_path: str = absolute path to ouptut .dcm file
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - deidentification_method: str = description stored in DeidentificationMethod
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep

    Outputs:
        - series_record: dict = linking table record of the series of this file (None if identifier missing, file not written)
    """

    # load the DICOM file
    dicom_data = pydicom.dcmread(input_path)

    # keep original series information for the linking table
    original_study_uid = str(dicom_data.get('StudyInstanceUID', ''))
    original_series_uid = str(dicom_data.get('SeriesInstanceUID', ''))
    series_information = {keyword: str(dicom_data.get(keyword, '')) for keyword in ('Modality', 'SeriesNumber', 'SeriesDescription', 'BurnedInAnnotation')}

    # pseudonymize the identifier, files without identifier are not written
    dicom_data, identifier_link = apply_pseudonym(dicom_data, identifier, key, deidentification_method)
    if identifier_link is None:
        return None

    # replace all instance UIDs (study, series, instance, frame of reference, references) consistently
    remap_uids(dicom_data, key)

    # remove private elements and anonymize other DICOM fields (excluding essential metadata)
    tags_to_keep = {Tag(tag) for tag in fields_to_keep.values()}
    remove_private_tags(dicom_data, tags_to_keep)
    sanitize_dataset(dicom_data, tags_to_keep, groups_to_keep)

    # ensure file meta data reflects the new dataset state
    ensure_file_meta(dicom_data)

    # save the anonymized DICOM file
    _save_dicom(dicom_data, output_path)

    # linking table record of the series
    series_record = {
        **{column: values[0] for column, values in identifier_link.items()},
        'Original StudyInstanceUID': original_study_uid,
        'Original SeriesInstanceUID': original_series_uid,
        'Pseudonymized StudyInstanceUID': str(dicom_data.StudyInstanceUID),
        'Pseudonymized SeriesInstanceUID': str(dicom_data.SeriesInstanceUID),
        **series_information,
    }

    return series_record

def pseudonymize_folders(walk, input_root: str, output_root: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, series_records: dict, skipped_files: list) -> None:
    """
    Pseudonymize the DICOM files of all folders and collect the linking table records (one per series).

    Inputs:
        - walk: iterator = os.walk of the input root (optionally wrapped in a progress bar)
        - input_root: str = absolute path to root of all DICOM folders
        - output_root: str = absolute path to output folder
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - deidentification_method: str = description stored in DeidentificationMethod
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
        - series_records: dict = linking table records, updated in place
        - skipped_files: list = files skipped because the identifier is missing, updated in place
    """

    for root, dirs, files in walk:

        # get .dcm files
        dcm_files = [file for file in files if file.lower().endswith('.dcm')]

        # if .dcm files are available
        if len(dcm_files) > 1:

            # create output folder
            rel_folder_path = os.path.relpath(root, input_root)
            output_folder = os.path.join(output_root, rel_folder_path)
            os.makedirs(output_folder, exist_ok=True)

            # iterate over DICOM files in this folder and pseudonymize them
            for dcm_file in dcm_files:
                input_path = os.path.join(root, dcm_file)
                output_path = os.path.join(output_folder, dcm_file)

                series_record = pseudonymize_dicom(input_path, output_path, identifier, key, deidentification_method, fields_to_keep, groups_to_keep)
                if series_record is None:
                    skipped_files.append(input_path)
                    continue

                # one linking table record per series (and output folder), counting its files
                record_key = (series_record[f'Original {identifier}'], series_record['Original SeriesInstanceUID'], rel_folder_path)
                if record_key not in series_records:
                    series_records[record_key] = {**series_record, 'Output folder': rel_folder_path, 'Number of files': 0}
                series_records[record_key]['Number of files'] += 1

def pseudonymization(input_root: str, output_root: str, profile: int, identifier: str, progress_bar: bool = PROGRESS_BAR, key_file: str = None, link_table: str = None) -> None:
    """
    Main function to pseudonymize a DICOM directory.

    Inputs:
        - input_root: str = absolute path to root of all DICOM folders
        - output_root: str = absolute path to output folder
        - profile: int = number corresponding to profile to be selected
        - identifier: str = DICOM keyword to be used as identifier
        - progress_bar: bool = (default = PROGRESS_BAR)
        - key_file: str = path to file containing the secret pseudonymization key, created if it does not exist
                          (default = None => key read from environment variable KEY_ENV_VARIABLE)
        - link_table: str = path to the linking table (.xlsx or .csv) between original and pseudo identifiers,
                            one row per DICOM series; must be located outside the output folder
    """

    # check identifier before doing anything
    if identifier not in IDENTIFIERS:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(IDENTIFIERS)})")

    # the key and the linking table must never be stored together with the pseudonymized data
    if link_table is None:
        raise SystemExit("No linking table given. Use --link-table PATH (outside the output folder).")
    if _is_inside(link_table, output_root):
        raise SystemExit(f"The linking table '{link_table}' must not be located inside the output folder '{output_root}'.")
    if key_file is not None and _is_inside(key_file, output_root):
        raise SystemExit(f"The key file '{key_file}' must not be located inside the output folder '{output_root}'.")
    key = load_key(key_file)

    # build output directories
    if not os.path.exists(output_root):
        os.mkdir(output_root)

    # linking table records (one per series) and files skipped because the identifier is missing
    series_records = {}
    skipped_files = []

    # overview of files and progress bar
    walk = os.walk(input_root)
    if progress_bar:
        walk = tqdm(os.walk(input_root), total=len(list(os.walk(input_root))))
    else:
        print("Pseudonymization...")

    # get all the field to keep
    fields_to_keep, groups_to_keep = select_profile(profile)
    deidentification_method = f"dicom_pseudo {TOOL_VERSION} profile {profile} {identifier} HMAC-SHA256"[:64]  # LO: max 64 chars

    # explore all folders (linking table always saved, also if an error occurs, so written files stay linked)
    try:
        pseudonymize_folders(walk, input_root, output_root, identifier, key, deidentification_method, fields_to_keep, groups_to_keep, series_records, skipped_files)
    finally:
        save_link_table(link_table, series_records, identifier)

    # report series flagged with burned-in annotations (pixel data may contain PHI, not handled here)
    burned_in = [record['Output folder'] for record in series_records.values() if record.get('BurnedInAnnotation', '').upper() == 'YES']
    if burned_in:
        print(f"WARNING: {len(burned_in)} series flagged with BurnedInAnnotation=YES, pixel data may contain PHI "
              "(check visually or redact with presidio.py), e.g.:")
        for folder in burned_in[:10]:
            print(" -", folder)

    # report files that could not be pseudonymized
    if skipped_files:
        print(f"WARNING: {len(skipped_files)} file(s) skipped because {identifier} is missing, e.g.:")
        for skipped_file in skipped_files[:10]:
            print(" -", skipped_file)

    print("Pseudonymization done.")
    print(" =>", output_root)
    print(" => linking table:", link_table)

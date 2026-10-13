""" IMPORTS """

# Pre-installed packages
import os
import hashlib
import hmac
import json
import secrets
from importlib.metadata import version, PackageNotFoundError
import argparse

# Tqdm [optional]
try:
    from tqdm import tqdm
    PROGRESS_BAR = True
except:
    print("INFO: Progress bar not available because tqdm is not installed.")
    PROGRESS_BAR = False

# Pandas
import pandas as pd

# Pydicom
import pydicom
from pydicom.dataset import FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


""" DEFINITION OF TAGS AND TAG GROUPS """

# Define DICOM tags for the information to be kept in all cases
FIELDS_TO_KEEP = {
    # Related to single DICOM file integrity
    'SpecificCharacterSet':     0x00080005,
    'ImageType':                0x00080008,
    'Manufacturer':             0x00080070,
    'SOPClassUID':              0x00080016,
    'SOPInstanceUID':           0x00080018,
    # Related to DICOM file integrity
    'StudyInstanceUID':         0x0020000d,      # replaced by random
    'SeriesInstanceUID':        0x0020000e,      # replaced by random
    'FrameOfReferenceUID':      0x00200052,      # replaced by random
    # Related to image
    'Modality':                 0x00080060,
    'SeriesNumber':             0x00200011,
    'AcquisitionNumber':        0x00200012,
    'InstanceNumber':           0x00200013,
    'PatientPosition':          0x00185100,
    'ImagePositionPatient':     0x00200032,
    'ImageOrientationPatient':  0x00200037,
    'SliceLocation':            0x00201041,
    'SliceThickness':           0x00180050,
    # Actual image
    'PixelData':                0x7fe00010,
    # Pseudonymization (pseudonym and de-identification flags, set by this tool)
    'PatientName':              0x00100010,
    'PatientID':                0x00100020,
    'PatientIdentityRemoved':   0x00120062,
    'DeidentificationMethod':   0x00120063}

# Define DICOM tag groups for the information to be kept in all cases
GROUPS_TO_KEEP = {
    # Related to DICOM file integrity
    0x0002,
    # Related to image
    0x0028,
}

# Define possible identifiers for one DICOM file (candidate tags, tried in order until a non-empty value is found)
IDENTIFIERS = {
    # Patient ID
    'PatientID':                [0x00100020],
    # Study ID
    'StudyID':                  [0x00200010],
    # AGFA ID: accession number, or custom AGFA private tag if not available
    'AgfaID':                   [0x00080050, 0x7fdd1013],
    'AccessionNumber':          [0x00080050, 0x7fdd1013]}

# Environment variable that can hold the secret pseudonymization key (alternative to --key-file)
KEY_ENV_VARIABLE = 'DICOM_PSEUDO_KEY'

# Version of this tool, recorded in the DeidentificationMethod of the pseudonymized files
try:
    TOOL_VERSION = version('dicom_pseudo')
except PackageNotFoundError:
    TOOL_VERSION = 'unknown'

# Value representation buckets for safe clearing
TEXT_VRS = {'AE', 'AS', 'CS', 'DA', 'DT', 'LO', 'LT', 'PN', 'SH', 'ST', 'TM', 'UC', 'UI', 'UR', 'UT'}
TEXT_NUMERIC_VRS = {'DS', 'IS'}
INT_VRS = {'SL', 'SS', 'UL', 'US', 'SV', 'UV'}
FLOAT_VRS = {'FL', 'FD'}
BINARY_VRS = {'OB', 'OD', 'OF', 'OL', 'OW', 'UN'}


""" FUNCTIONS """

def _select_profile(profile: int, fields_to_keep: dict = FIELDS_TO_KEEP, groups_to_keep: set = GROUPS_TO_KEEP) -> tuple[dict, set]:
    """
    Select the field to keep based on the profile.

    Inputs:
        - profile: int = number corresponding to profile to be selected
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep (default = FIELDS_TO_KEEP)
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep (default = GROUPS_TO_KEEP)

    Ouptuts:
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
    """

    # select profile from profile.json file
    if profile == 0:
        profile_filepath = os.path.join(os.path.dirname(__file__), 'profile.json')
        try:
            with open(profile_filepath, 'r') as profile_file:
                extra_fields_to_keep = json.load(profile_file)
        except json.JSONDecodeError as error:
            raise SystemExit(f"Invalid profile file '{profile_filepath}': {error}")

        # tag values may be given as int, hex string ('0x00101010') or keyword ('PatientAge')
        for keyword, tag in extra_fields_to_keep.items():
            try:
                extra_fields_to_keep[keyword] = int(Tag(tag))
            except Exception:
                raise SystemExit(f"Invalid tag '{tag}' for '{keyword}' in profile file '{profile_filepath}'.")

    # select profile 1 (age, sex, weight, height)
    elif profile == 1:    # profile for metadata
        extra_fields_to_keep = {
            'PatientAge':               0x00101010,
            'PatientSex':               0x00100040,
            'PatientWeight':            0x00101030,
            'PatientSize':              0x00101020,
            'PatientSizeCodeSequence':  0x00101021,
            'PatientBodyMassIndex':     0x00101022
        }

    # select profile 2 (profile 1 + time data)
    elif profile == 2:  # profile for metadata and timestamps
        extra_fields_to_keep = {
            'PatientAge':               0x00101010,
            'PatientSex':               0x00100040,
            'PatientWeight':            0x00101030,
            'PatientSize':              0x00101020,
            'PatientSizeCodeSequence':  0x00101021,
            'PatientBodyMassIndex':     0x00101022,
            
            'StudyDate':                0x00080020,
            'SeriesDate':               0x00080021
        }

    # select profile 3 (4D info)
    elif profile == 3:
        extra_fields_to_keep = {
            'ContentTime':              0x00080033,
            'AcquisitionTime':          0x00080032,
            'TimeStamp':                0x00191024
        }

    # other profile parameter inputs are incorrect
    else:
        raise SystemExit(f"Profile '{profile}' not supported. (0: user-defined, 1: pseudonymization, 2: pseudomymization + keep study time, 3: anonymization 4D)")

    # combine fields to keep with extra fields corresponding to profile (copies, the defaults must not be mutated)
    fields_to_keep = {**fields_to_keep, **extra_fields_to_keep}
    groups_to_keep = set(groups_to_keep)

    return fields_to_keep, groups_to_keep

def _load_key(key_file: str = None, key_env_variable: str = KEY_ENV_VARIABLE) -> bytes:
    """
    Load the secret key used to compute the pseudonyms (HMAC-SHA256).

    The key is read from the key file if given (a new random key is created if the file does not exist yet),
    otherwise from the environment variable. Without the key, pseudonyms cannot be recomputed or reversed by
    brute-forcing the (low-entropy) original identifiers, so the key must be stored securely and separately
    from the pseudonymized data.

    Inputs:
        - key_file: str = path to file containing the secret key (default = None)
        - key_env_variable: str = name of environment variable containing the secret key (default = KEY_ENV_VARIABLE)

    Outputs:
        - key: bytes = secret key
    """

    # read key from key file, or create a new random key file
    if key_file is not None:
        if os.path.exists(key_file):
            with open(key_file, 'r') as file:
                key = file.read().strip()
        else:
            key = secrets.token_hex(32)
            os.makedirs(os.path.dirname(os.path.abspath(key_file)), exist_ok=True)
            file_descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(file_descriptor, 'w') as file:
                file.write(key + '\n')
            print(f"WARNING: New pseudonymization key created at '{key_file}'. "
                  "Keep it secret, back it up, and never share it together with the pseudonymized data. "
                  "The same key is required to obtain the same pseudonyms in later runs.")

    # read key from environment variable
    else:
        key = os.environ.get(key_env_variable, '').strip()
        if not key:
            raise SystemExit(f"No pseudonymization key given. Use --key-file PATH (created if it does not exist) "
                             f"or set the environment variable {key_env_variable}.")

    if len(key) < 16:
        raise SystemExit("Pseudonymization key is too short (at least 16 characters required).")

    return key.encode()

def _get_identifier_value(dicom_data: pydicom.dataset.FileDataset, identifier: str, identifiers: dict = IDENTIFIERS) -> tuple[str, Tag]:
    """
    Get the value of the chosen identifier from the first candidate tag that holds a non-empty value.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object (in which the identifier is present)
        - identifier: str = name of the identifier (key of identifiers)
        - identifiers: dict = candidate tags for each identifier (default = IDENTIFIERS)

    Outputs:
        - value: str = identifier value (None if not found)
        - tag: Tag = tag in which the identifier value was found (None if not found)
    """

    if identifier not in identifiers:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(identifiers)})")

    for tag in identifiers[identifier]:
        element = dicom_data.get(Tag(tag), None)
        if element is None or element.value is None:
            continue
        value = element.value
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        value = str(value).strip(' \x00')
        if value:
            return value, Tag(tag)

    return None, None

def _pseudonym(value: str, key: bytes) -> str:
    """
    Compute the pseudonym of an identifier value as keyed hash (HMAC-SHA256).

    Inputs:
        - value: str = original identifier value
        - key: bytes = secret key

    Outputs:
        - pseudonym: str = hexadecimal pseudonym
    """

    return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()

def _hash_and_store(dicom_data: pydicom.dataset.FileDataset, identifier: str, key: bytes, deidentification_method: str = '', identifiers: dict = IDENTIFIERS) -> tuple[pydicom.dataset.FileDataset, dict]:
    """
    Pseudonymize the chosen identifier with a keyed hash, blank it in the DICOM, write the pseudonym in
    PatientID and PatientName, flag the file as de-identified, and return the mapping.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object (in which the identifier is present)
        - identifier: str = name of the identifier (key of identifiers)
        - key: bytes = secret key
        - deidentification_method: str = description stored in DeidentificationMethod (default = '')
        - identifiers: dict = candidate tags for each identifier (default = IDENTIFIERS)

    Outputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object
        - identifier_link: dict = link between identifier and pseudo identifier (None if identifier not found)
    """

    original_id, tag = _get_identifier_value(dicom_data, identifier, identifiers)

    if original_id is None:
        return dicom_data, None

    pseudonym = _pseudonym(original_id, key)

    # remove PHI from the DICOM and write the pseudonym, so images can be linked via the linking table
    dicom_data[tag].value = ''
    dicom_data.PatientID = pseudonym
    dicom_data.PatientName = pseudonym

    # flag the file as de-identified (DICOM PS3.15 Annex E)
    dicom_data.PatientIdentityRemoved = 'YES'
    dicom_data.DeidentificationMethod = deidentification_method

    identifier_link = {
        f'Original {identifier}': [original_id],
        f'Pseudonym {identifier}': [pseudonym]
    }

    return dicom_data, identifier_link

def _ensure_file_meta(dicom_data: pydicom.dataset.FileDataset) -> None:
    """
    Keep file meta information synchronized with the dataset content.
    """

    if dicom_data.file_meta is None:
        dicom_data.file_meta = FileMetaDataset()

    dicom_data.file_meta.MediaStorageSOPClassUID = dicom_data.SOPClassUID
    dicom_data.file_meta.MediaStorageSOPInstanceUID = dicom_data.SOPInstanceUID

    if 'TransferSyntaxUID' not in dicom_data.file_meta:
        dicom_data.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

def _clear_data_element(elem: pydicom.dataelem.DataElement, tags_to_keep: set[Tag], groups_to_keep: set[int]) -> None:
    """
    Clear the value of a DataElement while preserving its structural integrity.
    """

    if elem.tag in tags_to_keep or elem.tag.group in groups_to_keep:
        if elem.VR == 'SQ':
            for item in elem.value:
                _sanitize_dataset(item, tags_to_keep, groups_to_keep)
        return

    if elem.VR == 'SQ':
        for item in elem.value:
            _sanitize_dataset(item, tags_to_keep, groups_to_keep)
        elem.value = Sequence()
    elif elem.VR in TEXT_VRS:
        elem.value = ''
    elif elem.VR in TEXT_NUMERIC_VRS:
        elem.value = '0'
    elif elem.VR in INT_VRS:
        elem.value = 0
    elif elem.VR in FLOAT_VRS:
        elem.value = 0.0
    elif elem.VR in BINARY_VRS:
        elem.value = b''
    else:
        elem.value = ''

def _sanitize_dataset(dataset: pydicom.dataset.Dataset, tags_to_keep: set[Tag], groups_to_keep: set[int]) -> None:
    """
    Recursively sanitize all removable elements from a dataset without removing structural tags.
    """

    for elem in dataset:
        _clear_data_element(elem, tags_to_keep, groups_to_keep)

def _pseudonymize_dicom(input_path: str, output_path: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, mappings: tuple) -> tuple[dict, tuple]:
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
        - mappings: tuple = mappings between the UIDs of the .dcm files

    Outputs:
        - series_record: dict = linking table record of the series of this file (None if identifier missing, file not written)
        - mappings: tuple = mappings between the UIDs of the .dcm files
    """

    # load the DICOM file
    dicom_data = pydicom.dcmread(input_path)
    study_uid_mapping, series_uid_mapping, frame_of_reference_mapping = mappings

    # keep original series information for the linking table
    original_study_uid = str(dicom_data.get('StudyInstanceUID', ''))
    original_series_uid = str(dicom_data.get('SeriesInstanceUID', ''))
    series_information = {keyword: str(dicom_data.get(keyword, '')) for keyword in ('Modality', 'SeriesNumber', 'SeriesDescription')}

    # hash and store the identfiers, files without identifier are not written
    dicom_data, identifier_link = _hash_and_store(dicom_data, identifier, key, deidentification_method)
    if identifier_link is None:
        return None, mappings

    # retrieve study and series identifiers to ensure consistent UID replacement
    study_id = dicom_data.get('StudyID', None)
    series_number = dicom_data.get('SeriesNumber', None)
        
    # generate or reuse StudyInstanceUID
    if study_id not in study_uid_mapping:
        study_uid_mapping[study_id] = generate_uid()
    dicom_data.StudyInstanceUID = study_uid_mapping[study_id]

    # generate or reuse SeriesInstanceUID
    if (study_id, series_number) not in series_uid_mapping:
        series_uid_mapping[(study_id, series_number)] = generate_uid()
    dicom_data.SeriesInstanceUID = series_uid_mapping[(study_id, series_number)]

    # generate or reuse FrameOfReferenceUID to maintain spatial consistency across slices
    if (study_id, series_number) not in frame_of_reference_mapping:
        frame_of_reference_mapping[(study_id, series_number)] = generate_uid()
    dicom_data.FrameOfReferenceUID = frame_of_reference_mapping[(study_id, series_number)]

    # anonymize other DICOM fields (excluding essential metadata)
    tags_to_keep = {Tag(tag) for tag in fields_to_keep.values()}
    _sanitize_dataset(dicom_data, tags_to_keep, groups_to_keep)

    # ensure file meta data reflects the new dataset state
    _ensure_file_meta(dicom_data)

    # save the anonymized DICOM file
    dicom_data.save_as(output_path, write_like_original=False)
    mappings = study_uid_mapping, series_uid_mapping, frame_of_reference_mapping

    # linking table record of the series
    series_record = {
        **{column: values[0] for column, values in identifier_link.items()},
        'Original StudyInstanceUID': original_study_uid,
        'Original SeriesInstanceUID': original_series_uid,
        'Pseudonymized StudyInstanceUID': str(dicom_data.StudyInstanceUID),
        'Pseudonymized SeriesInstanceUID': str(dicom_data.SeriesInstanceUID),
        **series_information,
    }

    return series_record, mappings

def _is_inside(path: str, folder: str) -> bool:
    """
    Check whether a path is located inside a folder (or is the folder itself).
    """

    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([path, folder]) == folder

def _save_link_table(link_table: str, series_records: dict, identifier: str) -> None:
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
    key = _load_key(key_file)

    # build output directories
    if not os.path.exists(output_root):
        os.mkdir(output_root)

    # linking table records (one per series) and files skipped because the identifier is missing
    series_records = {}
    skipped_files = []
        
    # mapping required to maintain DICOM integrity
    study_uid_mapping = {}
    series_uid_mapping = {}
    frame_of_reference_mapping = {}
    mappings = (study_uid_mapping, series_uid_mapping, frame_of_reference_mapping)
    
    # overview of files and progress bar
    walk = os.walk(input_root)
    if progress_bar:
        walk = tqdm(os.walk(input_root), total=len(list(os.walk(input_root))))
    else:
        print("Pseudonymization...")
    
    # get all the field to keep
    fields_to_keep, groups_to_keep = _select_profile(profile)
    deidentification_method = f"dicom_pseudo {TOOL_VERSION} profile {profile} {identifier} HMAC-SHA256"[:64]  # LO: max 64 chars
    
    # explore all folders (linking table always saved, also if an error occurs, so written files stay linked)
    try:
        _pseudonymize_folders(walk, input_root, output_root, identifier, key, deidentification_method, fields_to_keep, groups_to_keep, mappings, series_records, skipped_files)
    finally:
        _save_link_table(link_table, series_records, identifier)

    # report files that could not be pseudonymized
    if skipped_files:
        print(f"WARNING: {len(skipped_files)} file(s) skipped because {identifier} is missing, e.g.:")
        for skipped_file in skipped_files[:10]:
            print(" -", skipped_file)

    print("Pseudonymization done.")
    print(" =>", output_root)
    print(" => linking table:", link_table)

def _pseudonymize_folders(walk, input_root: str, output_root: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, mappings: tuple, series_records: dict, skipped_files: list) -> None:
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
        - mappings: tuple = mappings between the UIDs of the .dcm files
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

                series_record, mappings = _pseudonymize_dicom(input_path, output_path, identifier, key, deidentification_method, fields_to_keep, groups_to_keep, mappings)
                if series_record is None:
                    skipped_files.append(input_path)
                    continue

                # one linking table record per series (and output folder), counting its files
                record_key = (series_record[f'Original {identifier}'], series_record['Original SeriesInstanceUID'], rel_folder_path)
                if record_key not in series_records:
                    series_records[record_key] = {**series_record, 'Output folder': rel_folder_path, 'Number of files': 0}
                series_records[record_key]['Number of files'] += 1


""" MAIN """


def main() -> None:
    """
    CLI entry point. Parse arguments then run pseudonymization workflow.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help='Path to the root folder containing DICOM files.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Path to output folder where to save pseudonymized DICOM files.')
    parser.add_argument('--profile', '-p', type=int, default=1, help='Selected profile (0: user-defined, 1: pseudonymization, 2: pseudomymization + keep study time, 3: anonymization 4D).')
    parser.add_argument('--identifier', '-i', type=str, default='StudyID', help='Identifier to be used for linking table (PatientID, StudyID, AgfaID/AccessionNumber).')
    parser.add_argument('--link-table', '-l', type=str, required=True, help='Path to the linking table (.xlsx or .csv) between original and pseudo identifiers, one row per DICOM series. Must be outside the output folder; existing tables are updated.')
    parser.add_argument('--key-file', '-k', type=str, default=None, help=f'Path to the secret key file used to compute the pseudonyms (created if it does not exist; keep it outside the output folder). If not given, the key is read from the environment variable {KEY_ENV_VARIABLE}.')
    args = parser.parse_args()
    
    # Input root
    input_root = args.input
    if '.dcm' in input_root:
        input_root = os.path.dirname(os.path.abspath(input_root))
        
    # Output root
    output_root = args.output
    if output_root is None:
        output_root = input_root + '_pseudonymized'
    output_root = output_root.replace(' ', '')
    
    # Profile
    profile = args.profile
    
    # Identifier
    identifier = args.identifier

    # Key file
    key_file = args.key_file

    # Linking table
    link_table = args.link_table

    # Pseudonymization
    pseudonymization(input_root, output_root, profile, identifier, key_file=key_file, link_table=link_table)


# python pseudonymization.py INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER)

if __name__ == '__main__':

    main()

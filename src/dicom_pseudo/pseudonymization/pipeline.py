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
from pydicom.uid import MediaStorageDirectoryStorage

# Pseudonymization modules
from .settings import IDENTIFIERS, LINKAGES, TOOL_VERSION, select_profile
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

def is_dicom_file(path: str) -> bool:
    """
    Check whether a file is a DICOM file based on its content (not its extension): files with the 'DICM'
    prefix after the 128-byte preamble (also if damaged, so that they are reported as failed), or '.dcm' files
    without preamble that pydicom can read as a dataset with a SOP Class UID. DICOMDIR files (media storage
    directories) are not considered as DICOM images.

    Inputs:
        - path: str = path to file

    Outputs:
        - is_dicom: bool = whether the file is a DICOM file to pseudonymize
    """

    try:
        with open(path, 'rb') as file:
            file.seek(128)
            has_prefix = file.read(4) == b'DICM'
    except OSError:
        return False

    # DICOM file format: exclude DICOMDIR based on the file meta information
    if has_prefix:
        try:
            file_meta = pydicom.filereader.read_file_meta_info(path)
        except Exception:
            return True
        return file_meta.get('MediaStorageSOPClassUID', None) != MediaStorageDirectoryStorage

    # .dcm file without preamble: raw dataset with a SOP Class UID
    if path.lower().endswith('.dcm'):
        try:
            dicom_data = pydicom.dcmread(path, stop_before_pixels=True, force=True, specific_tags=['SOPClassUID'])
        except Exception:
            return False
        return 'SOPClassUID' in dicom_data

    return False

def _save_dicom(dicom_data: pydicom.dataset.FileDataset, output_path: str) -> None:
    """
    Save a DICOM file in standard DICOM file format (preamble, prefix and file meta information).
    """

    if int(pydicom.__version__.split('.')[0]) >= 3:
        dicom_data.save_as(output_path, enforce_file_format=True)
    else:
        dicom_data.save_as(output_path, write_like_original=False)

def output_relative_path(dicom_data: pydicom.dataset.FileDataset) -> str:
    """
    Build the relative output path of a pseudonymized DICOM file from pseudonymized values only (nothing of the
    input path is kept, as folder and file names can contain identifiers, names or dates):
    <pseudonym (first 16 characters)>/<StudyInstanceUID>/<SeriesInstanceUID>/<SOPInstanceUID>.dcm

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = pseudonymized dicom file object

    Outputs:
        - relative_path: str = relative output path
    """

    patient_folder = str(dicom_data.PatientID)[:16]
    study_folder = str(dicom_data.get('StudyInstanceUID', '') or 'unknown_study')
    series_folder = str(dicom_data.get('SeriesInstanceUID', '') or 'unknown_series')
    return os.path.join(patient_folder, study_folder, series_folder, f'{dicom_data.SOPInstanceUID}.dcm')

def pseudonymize_dicom(input_path: str, output_root: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, linkage: str = 'patient', written_paths: set = None) -> dict:
    """
    Pseudonymize a single DICOM file.

    Inputs:
        - input_path: str = absolute path to .dcm file
        - output_root: str = absolute path to output folder (the file is saved in a pseudonymized sub folder, see output_relative_path)
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - deidentification_method: str = description stored in DeidentificationMethod
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
        - linkage: str = 'patient' or 'study' level pseudonyms and UIDs (default = 'patient')
        - written_paths: set = output paths already written in this run, updated in place (default = None)

    Outputs:
        - series_record: dict = linking table record of the series of this file (None if identifier missing, file not written)
    """

    # load the DICOM file
    dicom_data = pydicom.dcmread(input_path, force=True)
    if 'SOPClassUID' not in dicom_data or 'SOPInstanceUID' not in dicom_data:
        raise ValueError("not a valid DICOM dataset (damaged file or no SOP Class/Instance UID)")

    # keep original series information for the linking table
    original_study_uid = str(dicom_data.get('StudyInstanceUID', ''))
    original_series_uid = str(dicom_data.get('SeriesInstanceUID', ''))
    series_information = {keyword: str(dicom_data.get(keyword, '')) for keyword in ('Modality', 'SeriesNumber', 'SeriesDescription', 'BurnedInAnnotation')}

    # pseudonymize the identifier, files without identifier are not written
    dicom_data, identifier_link = apply_pseudonym(dicom_data, identifier, key, deidentification_method, linkage)
    if identifier_link is None:
        return None

    # replace all instance UIDs (study, series, instance, frame of reference, references) consistently
    # (study-level linkage: UIDs mapped per study, so that UIDs shared between studies do not link them)
    remap_uids(dicom_data, key, scope=original_study_uid if linkage == 'study' else '')

    # remove private elements and anonymize other DICOM fields (excluding essential metadata)
    tags_to_keep = {Tag(tag) for tag in fields_to_keep.values()}
    remove_private_tags(dicom_data, tags_to_keep)
    sanitize_dataset(dicom_data, tags_to_keep, groups_to_keep)

    # ensure file meta data reflects the new dataset state
    ensure_file_meta(dicom_data)

    # output path built from pseudonymized values, an instance is only written once per run
    relative_path = output_relative_path(dicom_data)
    output_path = os.path.join(output_root, relative_path)
    if written_paths is not None:
        if output_path in written_paths:
            raise ValueError("duplicate SOPInstanceUID (instance already pseudonymized from another file in this run)")
        written_paths.add(output_path)

    # save the anonymized DICOM file (partially written files are removed)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        _save_dicom(dicom_data, output_path)
    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise

    # linking table record of the series
    series_record = {
        **{column: values[0] for column, values in identifier_link.items()},
        'Original StudyInstanceUID': original_study_uid,
        'Original SeriesInstanceUID': original_series_uid,
        'Pseudonymized StudyInstanceUID': str(dicom_data.StudyInstanceUID),
        'Pseudonymized SeriesInstanceUID': str(dicom_data.SeriesInstanceUID),
        **series_information,
        'Output folder': os.path.dirname(relative_path),
    }

    return series_record

def pseudonymize_folders(walk, input_root: str, output_root: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, series_records: dict, skipped_files: list, failed_files: list, linkage: str = 'patient') -> None:
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
        - failed_files: list = (file, error) of files that could not be pseudonymized, updated in place
        - linkage: str = 'patient' or 'study' level pseudonyms and UIDs (default = 'patient')
    """

    written_paths = set()

    for root, dirs, files in walk:

        # get DICOM files (detected by content, with or without .dcm extension; other files are not copied)
        dcm_files = sorted(file for file in files if is_dicom_file(os.path.join(root, file)))
        input_folder = os.path.relpath(root, input_root)

        # iterate over DICOM files in this folder and pseudonymize them
        for dcm_file in dcm_files:
            input_path = os.path.join(root, dcm_file)

            # files that cannot be pseudonymized are reported
            try:
                series_record = pseudonymize_dicom(input_path, output_root, identifier, key, deidentification_method, fields_to_keep, groups_to_keep, linkage, written_paths)
            except Exception as error:
                failed_files.append((input_path, f'{type(error).__name__}: {error}'))
                continue
            if series_record is None:
                skipped_files.append(input_path)
                continue

            # one linking table record per series (and input folder), counting its files
            record_key = (series_record[f'Original {identifier}'], series_record['Original SeriesInstanceUID'], input_folder, series_record['Output folder'])
            if record_key not in series_records:
                series_records[record_key] = {**series_record, 'Input folder': input_folder, 'Number of files': 0}
            series_records[record_key]['Number of files'] += 1

def pseudonymization(input_root: str, output_root: str, profile: int, identifier: str, progress_bar: bool = PROGRESS_BAR, key_file: str = None, link_table: str = None, linkage: str = 'patient') -> None:
    """
    Main function to pseudonymize a DICOM directory (or a single DICOM file).

    Inputs:
        - input_root: str = absolute path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = absolute path to output folder
        - profile: int = number corresponding to profile to be selected
        - identifier: str = DICOM keyword to be used as identifier
        - progress_bar: bool = (default = PROGRESS_BAR)
        - key_file: str = path to file containing the secret pseudonymization key, created if it does not exist
                          (default = None => key read from environment variable KEY_ENV_VARIABLE)
        - link_table: str = path to the linking table (.xlsx or .csv) between original and pseudo identifiers,
                            one row per DICOM series; must be located outside the output folder
        - linkage: str = 'patient' (studies of the same patient share the pseudonym) or 'study' (one pseudonym
                         per study, studies of the same patient cannot be linked without the key) (default = 'patient')
    """

    # check identifier and linkage before doing anything
    if identifier not in IDENTIFIERS:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(IDENTIFIERS)})")
    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")

    # input and output must be separate folders (otherwise original files could be overwritten, or outputs
    # pseudonymized again in later runs)
    if not os.path.exists(input_root):
        raise SystemExit(f"Input '{input_root}' does not exist.")
    single_file = os.path.basename(input_root) if os.path.isfile(input_root) else None
    input_folder = os.path.dirname(os.path.abspath(input_root)) if single_file else input_root
    if single_file:
        if os.path.realpath(output_root) == os.path.realpath(input_folder):
            raise SystemExit(f"The output folder '{output_root}' must differ from the folder of the input file.")
    elif _is_inside(output_root, input_folder) or _is_inside(input_folder, output_root):
        raise SystemExit(f"The output folder '{output_root}' and the input folder '{input_folder}' must not be located inside each other.")

    # the key and the linking table must never be stored together with the pseudonymized data
    if link_table is None:
        raise SystemExit("No linking table given. Use --link-table PATH (outside the output folder).")
    if _is_inside(link_table, output_root):
        raise SystemExit(f"The linking table '{link_table}' must not be located inside the output folder '{output_root}'.")
    if key_file is not None and _is_inside(key_file, output_root):
        raise SystemExit(f"The key file '{key_file}' must not be located inside the output folder '{output_root}'.")
    key = load_key(key_file)

    # build output directories
    os.makedirs(output_root, exist_ok=True)

    # linking table records (one per series), files skipped because the identifier is missing, failed files
    series_records = {}
    skipped_files = []
    failed_files = []

    # overview of files and progress bar (a single input file is processed as a folder containing only this file)
    if single_file:
        walk = [(input_folder, [], [single_file])]
    else:
        walk = os.walk(input_folder)
        if progress_bar:
            walk = tqdm(os.walk(input_folder), total=len(list(os.walk(input_folder))))
    if not progress_bar or single_file:
        print("Pseudonymization...")

    # get all the field to keep
    fields_to_keep, groups_to_keep = select_profile(profile)
    deidentification_method = f"dicom_pseudo {TOOL_VERSION} profile {profile} {identifier} {linkage}-level HMAC-SHA256"[:64]  # LO: max 64 chars

    # explore all folders (linking table always saved, also if an error occurs, so written files stay linked)
    try:
        pseudonymize_folders(walk, input_folder, output_root, identifier, key, deidentification_method, fields_to_keep, groups_to_keep, series_records, skipped_files, failed_files, linkage)
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
    if failed_files:
        print(f"WARNING: {len(failed_files)} file(s) could not be pseudonymized (not written), e.g.:")
        for failed_file, error in failed_files[:10]:
            print(" -", failed_file, '->', error)

    # summary
    number_of_files = sum(record['Number of files'] for record in series_records.values())
    print(f"{number_of_files} file(s) in {len(series_records)} series pseudonymized.")

    print("Pseudonymization done.")
    print(" =>", output_root)
    print(" => linking table:", link_table)

"""
Pseudonymization of DICOM files: one pseudonymized DICOM file per input file.
"""

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

# Core modules
from ..core.settings import IDENTIFIERS, LINKAGES, TOOL_NAME, TOOL_VERSION, select_profile
from ..core.pseudonym import load_key
from ..core.identity import identify
from ..core.files import find_dicom_files, save_dicom
from ..core.paths import check_paths
from ..core.linking_table import link_record, add_record, save_link_table
from ..core.report import report

# Pseudonymization modules
from .deidentification import write_pseudonym, remap_uids
from .sanitization import remove_private_tags, sanitize_dataset, ensure_file_meta


""" FUNCTIONS """

def pseudonymize_dicom(input_path: str, input_folder: str, output_root: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, linkage: str = 'patient', written_paths: set = None) -> dict:
    """
    Pseudonymize a single DICOM file, saved as <output>/<pseudonym[:16]>/<StudyInstanceUID>/<SeriesInstanceUID>/<SOPInstanceUID>.dcm
    (pseudonymized values only).

    Inputs:
        - input_path: str = path to DICOM file
        - input_folder: str = relative input folder of the file (stored in the linking table)
        - output_root: str = path to output folder
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - deidentification_method: str = description stored in DeidentificationMethod
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
        - linkage: str = 'patient' or 'study' level pseudonyms and UIDs (default = 'patient')
        - written_paths: set = output paths already written in this run, updated in place (default = None)

    Outputs:
        - record: dict = linking table record of the series of this file (None if identifier missing, file not written)
    """

    # load the DICOM file
    dicom_data = pydicom.dcmread(input_path, force=True)
    if 'SOPClassUID' not in dicom_data or 'SOPInstanceUID' not in dicom_data:
        raise ValueError("not a valid DICOM dataset (damaged file or no SOP Class/Instance UID)")

    # identity of the series and its linking table record (from the original data), files without identifier are not written
    identity = identify(dicom_data, identifier, key, linkage)
    if identity is None:
        return None
    record = link_record(identity, dicom_data, input_folder)

    # write the pseudonym, replace all instance UIDs (study, series, instance, frame of reference, references) consistently
    write_pseudonym(dicom_data, identity, deidentification_method)
    remap_uids(dicom_data, key, identity.uid_scope)

    # remove private elements and anonymize other DICOM fields (excluding essential metadata)
    tags_to_keep = {Tag(tag) for tag in fields_to_keep.values()}
    remove_private_tags(dicom_data, tags_to_keep)
    sanitize_dataset(dicom_data, tags_to_keep, groups_to_keep)

    # ensure file meta data reflects the new dataset state
    ensure_file_meta(dicom_data)

    # output path built from pseudonymized values, an instance is only written once per run
    output_path = os.path.join(output_root, identity.output_folder, f'{dicom_data.SOPInstanceUID}.dcm')
    if written_paths is not None:
        if output_path in written_paths:
            raise ValueError("duplicate SOPInstanceUID (instance already pseudonymized from another file in this run)")
        written_paths.add(output_path)

    # save the pseudonymized DICOM file
    save_dicom(dicom_data, output_path)

    return record

def pseudonymization(input_root: str, output_root: str, profile: int, identifier: str, progress_bar: bool = PROGRESS_BAR, key_file: str = None, link_table: str = None, linkage: str = 'patient') -> None:
    """
    Main function to pseudonymize a DICOM directory (or a single DICOM file).

    Inputs:
        - input_root: str = path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = path to output folder
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

    # check inputs and locations before doing anything, load the key
    if identifier not in IDENTIFIERS:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(IDENTIFIERS)})")
    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")
    input_folder, single_file = check_paths(input_root, output_root, link_table, key_file)
    key = load_key(key_file)
    os.makedirs(output_root, exist_ok=True)

    # fields to keep and description of the de-identification
    fields_to_keep, groups_to_keep = select_profile(profile)
    deidentification_method = f"{TOOL_NAME} {TOOL_VERSION} profile {profile} {identifier} {linkage}-level"[:64]  # LO: max 64 chars

    # DICOM files (detected by content)
    dicom_files = find_dicom_files(input_folder, single_file)
    print(f"Pseudonymization of {len(dicom_files)} DICOM files...")

    # pseudonymize all files (linking table always saved, also if an error occurs, so written files stay linked)
    series_records, skipped, failed, written_paths = {}, [], [], set()
    try:
        for input_path in (tqdm(dicom_files) if progress_bar else dicom_files):
            try:
                record = pseudonymize_dicom(input_path, os.path.relpath(os.path.dirname(input_path), input_folder), output_root, identifier, key,
                                            deidentification_method, fields_to_keep, groups_to_keep, linkage, written_paths)
            except Exception as error:
                failed.append((input_path, f'{type(error).__name__}: {error}'))
                continue
            if record is None:
                skipped.append(input_path)
                continue
            add_record(series_records, record, identifier)
    finally:
        save_link_table(link_table, series_records, identifier)

    # report
    number_of_files = sum(record['Number of files'] for record in series_records.values())
    report(series_records, skipped, failed, identifier, f"{number_of_files} file(s) in {len(series_records)} series pseudonymized.", 'Pseudonymization', output_root, link_table)

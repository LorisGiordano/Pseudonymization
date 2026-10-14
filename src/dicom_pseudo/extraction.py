""" IMPORTS """

# Pre-installed packages
import os
import shutil
import json
import tempfile
import argparse
from collections import Counter, defaultdict

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
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence

# Dicom2nifti (its warnings are not shown, conversion errors are reported per series)
import logging
import dicom2nifti
logging.getLogger('dicom2nifti').setLevel(logging.ERROR)

# Pseudonymization modules (same profiles, identifiers, pseudonyms, UIDs, output structure and linking table)
from dicom_pseudo.pseudonymization.settings import FIELDS_TO_KEEP, IDENTIFIERS, KEY_ENV_VARIABLE, LINKAGES, profile_descriptions, select_profile
from dicom_pseudo.pseudonymization.pseudonym import load_key, get_identifier_value, compute_pseudonyms, pseudo_uid
from dicom_pseudo.pseudonymization.pipeline import check_paths, is_dicom_file, series_relative_folder
from dicom_pseudo.pseudonymization.linking_table import save_link_table


""" DEFINITION OF TIME STAMPS """

# DICOM keywords that can be used for 4D data reconstruction (tried in this order by the automatic detection):
#   - TemporalPositionIdentifier: temporal position of the image
#   - NumberOfTemporalPositions: number of time points, temporal position derived from the order of the images
#     (k-th image at a spatial position, sorted by InstanceNumber = time point k)
#   - ContentTime, AcquisitionTime, TimeStamp (GE private): time stamps
TIME_STAMP_FIELDS = {
    'TemporalPositionIdentifier':   0x00200100,
    'NumberOfTemporalPositions':    0x00200105,
    'ContentTime':                  0x00080033,
    'AcquisitionTime':              0x00080032,
    'TimeStamp':                    0x00191024
}


""" FUNCTIONS """

def _json_value(value):
    """
    Convert a DICOM value to a JSON serializable value.
    """

    if isinstance(value, Sequence):
        return [{elem.keyword or str(elem.tag): _json_value(elem.value) for elem in item} for item in value]
    if isinstance(value, (list, tuple, MultiValue)):
        return [_json_value(item) for item in value]
    if isinstance(value, (int, float, str)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    try:
        return float(value) if '.' in str(value) else int(value)
    except (TypeError, ValueError):
        return str(value)

def _get_metadata(dicom_data: pydicom.dataset.FileDataset, profile_fields: dict) -> dict:
    """
    Get the metadata of the profile (fields kept by the profile, on top of the fields kept in all cases).

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object
        - profile_fields: dict = dictionary of DICOM keywords (keys) and their tags (values) of the profile

    Outputs:
        - metadata: dict = metadata (JSON serializable)
    """

    metadata = {}
    for keyword, tag in profile_fields.items():
        if tag in dicom_data:
            metadata[keyword] = _json_value(dicom_data[tag].value)
    return metadata

def _group_by_series(dicom_files: list[str]) -> dict:
    """
    Group DICOM files by series (a folder can contain several series, a series can be split over folders).

    Inputs:
        - dicom_files: list[str] = paths to DICOM files

    Outputs:
        - series: dict = SeriesInstanceUID (keys) and list of (path, dataset without pixel data) (values)
    """

    series = defaultdict(list)
    for path in dicom_files:
        dicom_data = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        series[str(dicom_data.get('SeriesInstanceUID', ''))].append((path, dicom_data))
    for files in series.values():
        files.sort(key=lambda item: int(item[1].get('InstanceNumber', 0) or 0))
    return series

def _time_positions(files: list, time_stamp_keyword: str = None) -> tuple[str, list]:
    """
    Get the time position of each image of a series (for 4D data reconstruction).

    Automatic detection (if no time stamp keyword given), the first keyword giving more than one time point, each
    time point covering the same spatial positions (one volume per time point), is used:
        - TemporalPositionIdentifier
        - NumberOfTemporalPositions (time point = order of the image at its spatial position)
        - ContentTime, AcquisitionTime, TimeStamp

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - time_stamp_keyword: str = DICOM keyword to be used (default = None => automatic detection)

    Outputs:
        - keyword: str = keyword used (None if the series has no temporal dimension)
        - labels: list = time label of each image (None if the series has no temporal dimension)
    """

    if time_stamp_keyword is not None and time_stamp_keyword not in TIME_STAMP_FIELDS:
        raise SystemExit(f"Keyword '{time_stamp_keyword}' cannot be used as a time stamp keyword. (Use one of: {', '.join(TIME_STAMP_FIELDS)})")
    keywords = [time_stamp_keyword] if time_stamp_keyword else list(TIME_STAMP_FIELDS)

    for keyword in keywords:
        tag = TIME_STAMP_FIELDS[keyword]

        # time point derived from the number of temporal positions and the spatial position of the images
        if keyword == 'NumberOfTemporalPositions':
            number = files[0][1].get(tag, None)
            if number is None or int(number.value or 0) < 2:
                continue
            occurrences = Counter()
            labels = []
            for _, dicom_data in files:
                position = tuple(round(float(value), 3) for value in dicom_data.get('ImagePositionPatient', []))
                labels.append(occurrences[position])
                occurrences[position] += 1
            labels = [str(label) for label in labels]

        # time point read from the images
        else:
            if any(tag not in dicom_data or dicom_data[tag].value in (None, '') for _, dicom_data in files):
                continue
            labels = [str(dicom_data[tag].value).strip() for _, dicom_data in files]

        # valid if more than one time point, each time point covering the same spatial positions (a 3D volume
        # per time point, not e.g. one slice per time stamp of a 3D stack)
        positions_per_time = defaultdict(list)
        for label, (_, dicom_data) in zip(labels, files):
            positions_per_time[label].append(tuple(round(float(value), 3) for value in dicom_data.get('ImagePositionPatient', [])))
        volumes = {tuple(sorted(positions)) for positions in positions_per_time.values()}
        if len(positions_per_time) > 1 and len(volumes) == 1:
            return keyword, labels
        if time_stamp_keyword:
            raise ValueError(f"time stamp keyword '{keyword}' does not give time points covering the same spatial positions")

    return None, None

def _sort_labels(labels: set) -> list:
    """
    Sort time labels numerically if possible, otherwise alphabetically.
    """

    try:
        return sorted(labels, key=float)
    except ValueError:
        return sorted(labels)

def _convert(paths: list[str], output_file: str) -> None:
    """
    Convert DICOM files (one 3D volume) to NifTi, using a temporary folder containing only these files.
    """

    temp_folder = tempfile.mkdtemp()
    try:
        for i, path in enumerate(paths):
            shutil.copyfile(path, os.path.join(temp_folder, f'{i:06d}.dcm'))
        dicom2nifti.dicom_series_to_nifti(temp_folder, output_file)
    finally:
        shutil.rmtree(temp_folder, ignore_errors=True)

def extract_series(files: list, output_root: str, identifier: str, key: bytes, profile: int, profile_fields: dict, time_stamp: str = None, linkage: str = 'patient') -> dict:
    """
    Extract the image(s) and metadata of one series to a pseudonymized output folder.

    Output folder (same structure as the pseudonymized DICOM files): <pseudonym[:16]>/<StudyInstanceUID>/<SeriesInstanceUID>
        - image.nii.gz (3D), or <time point>.nii.gz and timestamps.json (4D, profile 3)
        - metadata.json (fields of the profile)

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - output_root: str = path to output folder
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - profile: int = number corresponding to profile to be selected
        - profile_fields: dict = fields of the profile (stored in metadata.json)
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)
        - linkage: str = 'patient' or 'study' level pseudonyms (default = 'patient')

    Outputs:
        - series_record: dict = linking table record of the series (None if identifier missing)
    """

    dicom_data = files[0][1]

    # pseudonyms and pseudonymized UIDs (identical to the pseudonymization of the DICOM files)
    original_id, _ = get_identifier_value(dicom_data, identifier)
    if original_id is None:
        return None
    original_study_uid = str(dicom_data.get('StudyInstanceUID', ''))
    original_series_uid = str(dicom_data.get('SeriesInstanceUID', ''))
    pseudo_id, patient_pseudo_id = compute_pseudonyms(original_id, original_study_uid, key, linkage)
    scope = original_study_uid if linkage == 'study' else ''
    pseudo_study_uid = pseudo_uid(original_study_uid, key, scope) if original_study_uid else ''
    pseudo_series_uid = pseudo_uid(original_series_uid, key, scope) if original_series_uid else ''
    output_folder = series_relative_folder(pseudo_id, pseudo_study_uid, pseudo_series_uid)
    output_directory = os.path.join(output_root, output_folder)
    os.makedirs(output_directory, exist_ok=True)

    # images: 4D (one NifTi per time point) for profile 3 if a temporal dimension is found, 3D otherwise
    paths = [path for path, _ in files]
    keyword, labels = _time_positions(files, time_stamp) if profile == 3 else (None, None)
    if keyword is None:
        _convert(paths, os.path.join(output_directory, 'image.nii.gz'))
        time_points = 0
    else:
        sorted_labels = _sort_labels(set(labels))
        for index, label in enumerate(sorted_labels):
            _convert([path for path, file_label in zip(paths, labels) if file_label == label], os.path.join(output_directory, f'{index}.nii.gz'))
        with open(os.path.join(output_directory, 'timestamps.json'), 'w') as file:
            json.dump({'keyword': keyword, 'timestamps': dict(enumerate(sorted_labels))}, file, indent=4)
        time_points = len(sorted_labels)

    # metadata of the profile, together with the image(s)
    metadata = _get_metadata(dicom_data, profile_fields)
    with open(os.path.join(output_directory, 'metadata.json'), 'w') as file:
        json.dump(metadata, file, indent=4)

    # linking table record of the series
    return {
        f'Original {identifier}': original_id,
        f'Pseudonym {identifier}': pseudo_id,
        f'Patient pseudonym {identifier}': patient_pseudo_id,
        'Linkage': linkage,
        'Original StudyInstanceUID': original_study_uid,
        'Original SeriesInstanceUID': original_series_uid,
        'Pseudonymized StudyInstanceUID': pseudo_study_uid,
        'Pseudonymized SeriesInstanceUID': pseudo_series_uid,
        **{keyword_: str(dicom_data.get(keyword_, '')) for keyword_ in ('Modality', 'SeriesNumber', 'SeriesDescription', 'BurnedInAnnotation')},
        'Output folder': output_folder,
        'Number of files': len(files),
        'Time points': time_points,
        'Time keyword': keyword or '',
        '_metadata': metadata,
    }

def _save_metadata_table(metadata_table: str, series_records: dict, identifier: str) -> None:
    """
    Save the overview table of the metadata (pseudonyms and profile fields only, no original identifiers),
    merged with the existing table if any.
    """

    rows = [{'Pseudonym': record[f'Pseudonym {identifier}'], 'Output folder': record['Output folder'], 'Modality': record['Modality'],
             'Time points': record['Time points'], **{key: json.dumps(value) if isinstance(value, (list, dict)) else value for key, value in record['_metadata'].items()}}
            for record in series_records.values()]
    df = pd.DataFrame(rows)
    if os.path.exists(metadata_table):
        df = pd.concat([pd.read_excel(metadata_table), df], ignore_index=True).drop_duplicates(subset=['Output folder'], keep='last')
    df.to_excel(metadata_table, index=False)

def extraction(input_root: str, output_root: str, profile: int, identifier: str, time_stamp: str = None, progress_bar: bool = PROGRESS_BAR, key_file: str = None, link_table: str = None, linkage: str = 'patient') -> None:
    """
    Main function to extract pseudonymized NifTi files and metadata from a DICOM directory.

    Inputs:
        - input_root: str = path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = path to output folder
        - profile: int = number corresponding to profile to be selected
        - identifier: str = DICOM keyword to be used as identifier
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)
        - progress_bar: bool = (default = PROGRESS_BAR)
        - key_file: str = path to file containing the secret pseudonymization key, created if it does not exist
                          (default = None => key read from environment variable KEY_ENV_VARIABLE)
        - link_table: str = path to the linking table (.xlsx or .csv), outside the output folder
        - linkage: str = 'patient' or 'study' level pseudonyms (default = 'patient')
    """

    # check inputs before doing anything
    if identifier not in IDENTIFIERS:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(IDENTIFIERS)})")
    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")
    if time_stamp is not None and time_stamp not in TIME_STAMP_FIELDS:
        raise SystemExit(f"Keyword '{time_stamp}' cannot be used as a time stamp keyword. (Use one of: {', '.join(TIME_STAMP_FIELDS)})")
    input_folder, single_file = check_paths(input_root, output_root, link_table, key_file)
    key = load_key(key_file)
    fields_to_keep, _ = select_profile(profile)
    profile_fields = {keyword: tag for keyword, tag in fields_to_keep.items() if keyword not in FIELDS_TO_KEEP}
    os.makedirs(output_root, exist_ok=True)

    # DICOM files (detected by content), grouped by series
    if single_file:
        dicom_files = [os.path.join(input_folder, single_file)]
    else:
        dicom_files = [os.path.join(root, file) for root, dirs, files in os.walk(input_folder) for file in sorted(files)
                       if is_dicom_file(os.path.join(root, file))]
    series = _group_by_series(dicom_files)
    print(f"Extraction of {len(series)} series ({len(dicom_files)} DICOM files)...")

    # extract all series (linking table always saved, also if an error occurs)
    series_records, skipped, failed = {}, [], []
    items = tqdm(series.items()) if progress_bar else series.items()
    try:
        for series_uid, files in items:
            input_folders = sorted({os.path.relpath(os.path.dirname(path), input_folder) for path, _ in files})
            try:
                record = extract_series(files, output_root, identifier, key, profile, profile_fields, time_stamp, linkage)
            except Exception as error:
                failed.append((input_folders, f'{type(error).__name__}: {error}'))
                continue
            if record is None:
                skipped.append(input_folders)
                continue
            record['Input folder'] = ';'.join(input_folders)
            series_records[(record[f'Original {identifier}'], series_uid, record['Output folder'])] = record
    finally:
        link_records = {key_: {column: value for column, value in record.items() if column != '_metadata'} for key_, record in series_records.items()}
        save_link_table(link_table, link_records, identifier)
        if series_records:
            _save_metadata_table(os.path.join(output_root, 'metadata.xlsx'), series_records, identifier)

    # report
    if skipped:
        print(f"WARNING: {len(skipped)} series skipped because {identifier} is missing, e.g.: {skipped[:5]}")
    if failed:
        print(f"WARNING: {len(failed)} series could not be converted, e.g.:")
        for folders, error in failed[:10]:
            print(" -", ';'.join(folders), '->', error)
    four_d = sum(1 for record in series_records.values() if record['Time points'])
    print(f"{len(series_records)} series extracted ({four_d} as 4D).")
    print("Extraction done.")
    print(" =>", output_root)
    print(" => linking table:", link_table)


""" MAIN """

def main():
    # Parser
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help='Path to the root folder containing DICOM files (detected by content), or to a single DICOM file.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Path to output folder where to save pseudonymized NifTi files, outside the input folder (default = INPUT_extracted next to the input).')
    parser.add_argument('--profile', '-p', type=int, default=1, help=f'Selected profile ({profile_descriptions()}).')
    parser.add_argument('--identifier', '-i', type=str, default='PatientID', choices=list(IDENTIFIERS), help='Identifier to be pseudonymized and used for the linking table (default = PatientID).')
    parser.add_argument('--timestamp', '-t', type=str, default=None, choices=list(TIME_STAMP_FIELDS), help='DICOM keyword to be used for 4D data reconstruction with profile 3 (default = automatic detection).')
    parser.add_argument('--linkage', type=str, default='patient', choices=list(LINKAGES), help="Linkage level of the pseudonyms: 'patient' (default) or 'study'.")
    parser.add_argument('--link-table', '-l', type=str, required=True, help='Path to the linking table (.xlsx or .csv) between original and pseudo identifiers, one row per DICOM series. Must be outside the output folder; existing tables are updated.')
    parser.add_argument('--key-file', '-k', type=str, default=None, help=f'Path to the secret key file used to compute the pseudonyms (created if it does not exist; keep it outside the output folder). If not given, the key is read from the environment variable {KEY_ENV_VARIABLE}.')
    args = parser.parse_args()

    # Input root (folder or single DICOM file)
    input_root = os.path.normpath(args.input)

    # Output root
    output_root = args.output
    if output_root is None:
        output_root = (os.path.splitext(input_root)[0] if os.path.isfile(input_root) else input_root) + '_extracted'

    # Extraction
    extraction(input_root, output_root, args.profile, args.identifier, args.timestamp, key_file=args.key_file, link_table=args.link_table, linkage=args.linkage)

# extract INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -t TIMESTAMP -l LINK_TABLE -k KEY_FILE --linkage LINKAGE

if __name__ == '__main__':

    main()

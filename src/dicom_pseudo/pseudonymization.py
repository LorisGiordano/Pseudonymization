""" IMPORTS """

# Pre-installed packages
import os
import hashlib
import json
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
    'PixelData':                0x7fe00010}

# Define DICOM tag groups for the information to be kept in all cases
GROUPS_TO_KEEP = {
    # Related to DICOM file integrity
    0x0002,
    # Related to image
    0x0028,
}

# Define possible identifiers for one DICOM file
IDENTIFIERS = {
    # Patient ID
    'PatientID':                0x00100020,
    # Study ID
    'StudyID':                  0x00200010,
    # AGFA ID
    'AgfaID':                   0x7fdd1013,      # custom
    'AccessionNumber':          0x00080050}

# Value representation buckets for safe clearing
TEXT_VRS = {'AE', 'AS', 'CS', 'DA', 'DT', 'LO', 'LT', 'PN', 'SH', 'ST', 'TM', 'UC', 'UI', 'UR', 'UT'}
TEXT_NUMERIC_VRS = {'DS', 'IS'}
INT_VRS = {'SL', 'SS', 'UL', 'US', 'SV', 'UV'}
FLOAT_VRS = {'FL', 'FD'}
BINARY_VRS = {'OB', 'OD', 'OF', 'OL', 'OW', 'UN'}


""" FUNCTIONS """

def _select_profile(profile: int, fields_to_keep: dict = FIELDS_TO_KEEP, groups_to_keep: dict = GROUPS_TO_KEEP) -> tuple[dict, set]:
    """
    Select the field to keep based on the profile.

    Inputs:
        - profile: int = number corresponding to profile to be selected
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep (default = FIELDS_TO_KEEP)
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep (default = GROUPS_TO_KEEP)

    Ouptuts:
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: dict = set of DICOM keyword groups of the fields to keep
    """

    # select profile from profile.json file
    if profile == 0:
        profile_filepath = os.path.join(os.path.dirname(__file__), 'profile.json')
        with open(profile_filepath, 'r') as profile_file:
            extra_fields_to_keep = json.load(profile_file)
        
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

    # update fields to keep to also store extra fields corresponding to profile
    fields_to_keep.update(extra_fields_to_keep)
    
    return fields_to_keep, groups_to_keep

def _hash_and_store(dicom_data: pydicom.dataset.FileDataset, identifier: str, identifiers: dict = IDENTIFIERS) -> tuple[pydicom.dataset.FileDataset, dict]:
    """
    Hash the chosen identifier, blank it in the DICOM, and return the mapping.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object (in which the identifier is present)
        - identifier: str = DICOM keyword to be used as identifier
        - local_id_excel_path: str = absolute path to Excel file containing linking table

    Outputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object
        - identifier_link: dict = link between identifier and pseudo identifier
    """

    # select patient ID as identifier
    if identifier == 'PatientID':
        # get keyword values
        tag = identifiers['PatientID']
        original_patient_id = dicom_data.get('PatientID', None)
        hashed_patient_id = None

        # hash the PatientID if it exists
        if original_patient_id:
            hashed_patient_id = hashlib.sha256(original_patient_id.encode()).hexdigest()
            dicom_data.PatientID = ''  # remove PHI from the DICOM
            identifier_link = {
                'Original PatientID': [original_patient_id],
                'Hashed PatientID': [hashed_patient_id]
            }
        else:
            print(f"File could not be pseudonymized us PatientID as identifier.")
            identifier_link = None

    # select study ID as identifier
    elif identifier == 'StudyID':
        # get keyword values
        tag = identifiers['StudyID']
        original_study_id = dicom_data.get('StudyID', None)
        hashed_study_id = None

        # hash the StudyID if it exists
        if original_study_id:
            hashed_study_id = hashlib.sha256(original_study_id.encode()).hexdigest()
            dicom_data.StudyID = ''
            identifier_link = {
                'Original StudyID': [original_study_id],
                'Hashed StudyID': [hashed_study_id]
            }
        else:
            print(f"File could not be pseudonymized using StudyID as identifier.")
            identifier_link = None

    # select AGFA ID as identifier
    elif identifier == 'AgfaID':

        # get keyword value from accession number
        try:
            tag = identifiers['AccessionNumber']
            original_agfa_id = dicom_data[tag].value
        # if not available, try custom ID
        except:
            try:
                tag = identifiers['AgfaID']
                original_agfa_id = dicom_data[tag].value
            except:
                original_agfa_id = None
        hashed_agfa_id = None

        # hash the AgfaID if it exists
        if original_agfa_id:
            hashed_agfa_id = hashlib.sha256(original_agfa_id.encode()).hexdigest()
            dicom_data[tag].value = ''
            identifier_link = {
                'Original AgfaID': [original_agfa_id],
                'Hashed AgfaID': [hashed_agfa_id]
            }
        else:
            print(f"File could not be pseudonymized using AgfaID as identifier.")
            identifier_link = None

    # unavailable identifier
    else:
        raise Exception(f"Keyword identifier '{identifier}' cannot be used as an identifier.")
        
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

def _pseudonymize_dicom(input_path: str, output_path: str, identifier: str, fields_to_keep: dict, groups_to_keep: set, mappings: tuple) -> tuple[dict, tuple]:
    """
    Pseudonymize a single DICOM file.

    Inputs:
        - input_path: str = absolute path to .dcm file
        - output_path: str = absolute path to ouptut .dcm file
        - identifier: str = DICOM keyword to be used as identifier
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
        - mappings: tuple = mappings between the UIDs of the .dcm files

    Outputs:
        - identifier_link: dict = link between identifier and pseudo identifier
        - mappings: tuple = mappings between the UIDs of the .dcm files
    """

    # load the DICOM file
    dicom_data = pydicom.dcmread(input_path)
    study_uid_mapping, series_uid_mapping, frame_of_reference_mapping = mappings
    
    # hash and store the identfiers
    dicom_data, identifier_link = _hash_and_store(dicom_data, identifier)

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
        
    return identifier_link, mappings

def pseudonymization(input_root: str, output_root: str, profile: int, identifier: str, progress_bar: bool = PROGRESS_BAR) -> None:
    """
    Main function to pseudonymize a DICOM directory.

    Inputs:
        - input_root: str = absolute path to root of all DICOM folders
        - output_root: str = absolute path to output folder
        - profile: int = number corresponding to profile to be selected
        - identifier: str = DICOM keyword to be used as identifier
        - progress_bar: bool = (default = PROGRESS_BAR)
    """
    
    # build output directories
    if not os.path.exists(output_root):
        os.mkdir(output_root)
    excel_path = os.path.join(output_root, 'table.xlsx')
    
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
    
    # explore all folders
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
            identifier_link = {"Hashed "+identifier: ["error_occured"]}
            for dcm_file in dcm_files:
                input_path = os.path.join(root, dcm_file)
                output_path = os.path.join(output_folder, dcm_file)

                identifier_link, mappings = _pseudonymize_dicom(input_path, output_path, identifier, fields_to_keep, groups_to_keep, mappings)
            
            # save identifier link between original and pseudo IDs
            if identifier_link is not None:
                try:
                    existing_data = pd.read_excel(excel_path)
                    df = pd.concat([existing_data, pd.DataFrame(identifier_link)], ignore_index=True)
                    df = df.drop_duplicates()
                except FileNotFoundError:
                    df = pd.DataFrame(identifier_link)
                df.to_excel(excel_path, index=False)
            else:
                raise Exception("Error occured in the pseudnymization, identification field missing.")
                
    print("Pseudonymization done.")
    print(" =>", output_root)


""" MAIN """


def main() -> None:
    """
    CLI entry point. Parse arguments then run pseudonymization workflow.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help='Path to the root folder containing DICOM files.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Path to output folder where to save pseudonymized DICOM files.')
    parser.add_argument('--profile', '-p', type=int, default=1, help='Selected profile (0: user-defined, 1: pseudonymization, 2: pseudomymization + keep study time, 3: anonymization 4D).')
    parser.add_argument('--identifier', '-i', type=str, default='StudyID', help='Identifier to be used for linking table (PatientID, StudyID, AccessionNumbur/AgfaID).')
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
    
    # Pseudonymization
    pseudonymization(input_root, output_root, profile, identifier)


# python pseudonymization.py INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER)

if __name__ == '__main__':

    main()

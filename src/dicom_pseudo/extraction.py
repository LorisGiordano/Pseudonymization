""" IMPORTS """

# Pre-installed packages
import os
import shutil
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

# Dicom2nifti
import dicom2nifti

# Sitk
try:
    import SimpleITK as sitk
    ALLOW_4D = True
except:
    ALLOW_4D = False


""" FUNCTIONS """

def _select_profile(profile: int) -> dict:
    """
    Select the field to keep based on the profile.

    Inputs:
        - profile: int = number corresponding to profile to be selected
            - profile 0 = user-defined via profile.json
            - profile 1 = pseudonymization (age, sex, weight, height)
            - profile 2 = pseudonymization (age, sex, weight, height, time of study)
            - profile 3 = 4D data with full anonymization

    Outputs:
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
    """

    # select profile from profile.json file
    if profile == 0:
        profile_filepath = os.path.join(os.path.dirname(__file__), 'pseudonymization', 'config', 'profile.json')
        with open(profile_filepath, 'r') as profile_file:
            fields_to_keep = json.load(profile_file)
        
    # select profile 1 (age, sex, weight, height)
    elif profile == 1:    # profile for metadata
        fields_to_keep = {
            'PatientAge':               0x00101010,
            'PatientSex':               0x00100040,
            'PatientWeight':            0x00101030,
            'PatientSize':              0x00101020,
            'PatientSizeCodeSequence':  0x00101021,
            'PatientBodyMassIndex':     0x00101022
        }

    # select profile 2 (profile 1 + time data)
    elif profile == 2:  # profile for metadata and timestamps
        fields_to_keep = {
            'PatientAge':               0x00101010,
            'PatientSex':               0x00100040,
            'PatientWeight':            0x00101030,
            'PatientSize':              0x00101020,
            'PatientSizeCodeSequence':  0x00101021,
            'PatientBodyMassIndex':     0x00101022,
            
            'StudyDate':                0x00080020,
            'SeriesDate':               0x00080021
        }

    # select profile 3 (4D info with full anonymization)
    elif profile == 3:
        fields_to_keep = {
        }

    # other profile parameter inputs are incorrect
    else:
        raise SystemExit(f"Profile '{profile}' not supported. (0: user-defined, 1: pseudonymization, 2: pseudomymization + keep study time, 3: anonymization 4D)")
    
    return fields_to_keep

def _select_identifier(dicom_data: pydicom.dataset.FileDataset, identifier: str, local_id_excel_path: str) -> tuple[str, int]:
    """
    Get and save pseudo-local identifier link.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object (in which the identifier is present)
        - identifier: str = DICOM keyword to be used as identifier
        - local_id_excel_path: str = absolute path to Excel file containing linking table

    Outputs:
        - pseudo_id: str = DICOM keyword to be used as identifier
        - local_id: int = local identifier (corresponding to index in the linking table)
    """

    # select identifier
    if identifier == 'PatientID':
        identifier_value = dicom_data.get('PatientID', None)
    elif identifier == 'StudyID':
        identifier_value = dicom_data.get('StudyID', None)
    elif identifier == 'AgfaID':
        identifier_value = dicom_data.get('AccessionNumber', None)
        if identifier_value is None:
            try:
                identifier_value = dicom_data[0x7fdd1013]
            except:
                identifier_value = None
    if identifier_value is None:
        raise Exception(f"Selected identifier {identifier} not found in DICOM file.")

    # save identifier link between pseudo and local IDs
    pseudo_id = identifier_value
    try:
        existing_local_id = pd.read_excel(local_id_excel_path)
        local_id = len(existing_local_id) + 1
        local_table = {identifier: pseudo_id, 'LocalID': local_id}
        df = pd.concat([existing_local_id, pd.DataFrame(local_table, index=[0])], ignore_index=True)
        df = df.drop_duplicates()
    except FileNotFoundError:
        local_id = 1
        local_table = {identifier: pseudo_id, 'LocalID': local_id}
        df = pd.DataFrame(local_table, index=[0])
    df.to_excel(local_id_excel_path, index=False)
        
    return pseudo_id, local_id

def _get_and_save_metadata(dicom_data: pydicom.dataset.FileDataset, fields_to_keep: dict, local_id: int, output_directory: str, metadata_excel_path: str) -> None:
    """
    Get and save the metadata in overview table and locally for each image.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - local_id: int = local identifier
        - output_directory: str = absolute path to output directory
        - metadata_excel_path: str = absolute path to Excel file containing metadata table
    """

    # build metadata dictionary
    metadata = {'LocalID': local_id}
    keywords_kept = list(fields_to_keep.keys())
    for elem in dicom_data.iterall():
        if elem.keyword in keywords_kept:
            metadata[elem.keyword] = elem.value
    
    # save database of all metadata
    try:
        existing_metadata = pd.read_excel(metadata_excel_path)
        df = pd.concat([existing_metadata, pd.DataFrame(metadata, index=[0])], ignore_index=True)
        df = df.drop_duplicates()
    except FileNotFoundError:
        df = pd.DataFrame(metadata, index=[0])
    df.to_excel(metadata_excel_path, index=False)
    
    # save metadata in json file together with image
    metadata.pop('LocalID')
    metadata_filepath = os.path.join(output_directory, 'metadata.json')
    with open(metadata_filepath, 'w') as metadata_file:
        json.dump(metadata, metadata_file)

def _4D_select_time_stamp_tag(time_stamp_keyword: str, dcm_files: list[str] = None, auto_find_correct_timestamp: bool = True) -> int:
    """
    Select the time stamp tag (for 4D data reconstruction from .dcm files).

    Inputs:
        - time_stamp_keyword: str = DICOM keyword to be used for 4D data reconstruction (can be None)
        - dcm_files: list[str] = list of absolute path to .dcm files
        - auto_find_correct_timestamp: bool = whether or not to find the correct timestamp tag based on file distribution (default = True)

    Outputs:
        - time_stamp_tag: int = DICOM tag to be used for 4D data reconstruction
    """

    time_stamp_fields = {
        'ContentTime':              0x00080033,
        'AcquisitionTime':          0x00080032,
        'TimeStamp':                0x00191024
    }
    
    # if time stamp keyword given, select corresponding tag
    if time_stamp_keyword:
        if time_stamp_keyword in time_stamp_fields.keys():
            time_stamp_tag = time_stamp_fields[time_stamp_keyword]
        else:
            raise Exception(f"Keyword '{time_stamp_keyword}' cannot be used as a time stamp keyword.")
    
    # if not, find correct time stamp
    else:
        
        # get all available time stamp references
        if dcm_files is None:
            raise Exception("No .dcm file list found.")
        dicom_data = pydicom.dcmread(dcm_files[0])
        possible_time_stamp_tags = []
        for keyword, tag in time_stamp_fields.items():
            time_stamp = dicom_data.get(keyword, None)
            if time_stamp:
                possible_time_stamp_tags.append(tag)
                    
        # if no time stamp tag found, raise error
        if not possible_time_stamp_tags:
            raise Exception(f"No reference for time stamp could be retrieved in dicom file.")
            
        # if only one possible time stamp tag, select that one
        elif len(possible_time_stamp_tags) == 1:
            time_stamp_tag = possible_time_stamp_tags[0]
            
        # if more than 1 time stamp tag found, find correct time stamp or select first one
        else:
            
            # if trying to find correct time stamp
            if auto_find_correct_timestamp:
            
                # get amount of images per time stamp for all the possible time stamp keywords
                time_stamp_tag = None
                for possible_time_stamp_tag in possible_time_stamp_tags:
                    images_per_timestamp = {}
                    for dcm_file in dcm_files:
                        
                        # load the DICOM file
                        dicom_data = pydicom.dcmread(dcm_file)
                        
                        # get timestamp
                        time_stamp = dicom_data[possible_time_stamp_tag].value
                        time_stamp = str(time_stamp)
                        time_stamp.replace('.', '_')
                        
                        # add one count to corresponding timestamp
                        if not (time_stamp in images_per_timestamp.keys()):
                            images_per_timestamp[time_stamp] = 1
                        else:
                            images_per_timestamp[time_stamp] += 1
                            
                    # if as much images found for each time stamp, select this time stamp tag
                    if len(set(images_per_timestamp.values())) <= 1:
                        time_stamp_tag = possible_time_stamp_tag
                        break
                        
                if time_stamp_tag is None:
                    raise Exception("No valid time stamp keyword could be found.")
            
            # if select first one
            else:
                time_stamp_tag = possible_time_stamp_tags[0]
                print("INFO: Multiple possible time stamp tags found, using", time_stamp_tag)

    return time_stamp_tag

def _4D_get_and_organize_time_stamps(dicom_directory: str, time_stamp_keyword: str, temp_folder: str) -> list[str]:
    """
    Get and organize the time stamps by grouping dicom files according to time stamp keyword.

    Inputs:
        - dicom_directory: str = absolute path to DICOM directory
        - time_stamp_keyword: str = DICOM keyword to be used for 4D data reconstruction (can be None)
        - temp_folder: str = absolute path to tempory folder to group .dcm files per time stamp

    Outputs:
        - time_stamps: list[str] = list of all the time stamps
    """

    # Get dicom folder
    dicom_directory = os.path.dirname(dicom_directory)
    # Separate .dcm files per time stamp
    for root, dirs, files in os.walk(dicom_directory):
        # Get .dcm files
        dcm_files = [os.path.join(root, file) for file in files if file.lower().endswith('.dcm')]
        if len(dcm_files) > 1:
            
            # Select time stamp tag
            time_stamp_tag = _4D_select_time_stamp_tag(time_stamp_keyword, dcm_files)
            time_stamps = []
                
            # Go over all .dcm files
            for dcm_file in dcm_files:
                
                # Load the DICOM file
                dicom_data = pydicom.dcmread(dcm_file)
                
                # Get timestamp
                time_stamp = dicom_data[time_stamp_tag].value
                time_stamp = str(time_stamp)
                time_stamp.replace('.', '_')
                
                # Copy file to corresponding time stamp folder
                basename = os.path.basename(dcm_file)
                if not (time_stamp in time_stamps):
                    os.makedirs(os.path.join(temp_folder, time_stamp))
                    time_stamps.append(time_stamp)
                shutil.copyfile(dcm_file, os.path.join(temp_folder, time_stamp, basename))
                
    return time_stamps

def _4D_save_time_stamps(time_stamps: list[str], output_directory: str) -> list[str]:
    """
    Save time stamps.

    Inputs:
        - time_stamps: list[str] = list of all the time stamps
        - output_directory: str = absolute path to ouptut directory

    Outputs:
        - sorted_time_stamps: list[str] = list of time stamps in increasing order
    """

    # save sorted time stamps to json file
    sorted_time_stamps = sorted(time_stamps)
    time_stamps_dict = dict(zip(range(len(sorted_time_stamps)), sorted_time_stamps))
    time_stamps_filepath = os.path.join(output_directory, 'timestamps.json')
    with open(time_stamps_filepath, 'w') as time_stamps_file:
        json.dump(time_stamps_dict, time_stamps_file)
        
    return sorted_time_stamps

def _extract_image_and_metadata(dicom_directory: str, output_directory: str, identifier: str, fields_to_keep: dict, metadata_excel_path: str, local_id_excel_path: str) -> None:
    """
    Extract images and metadata for each DICOM folder.

    Inputs:
        - dicom_directory: str = absolute path to DICOM directory
        - output_directory: str = absolute path to ouptut directory
        - identifier: str = DICOM keyword to be used as identifier
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - metadata_excel_path: str = absolute path to Excel file containing metadata table
        - local_id_excel_path: str = absolute path to Excel file containing linking table
    """

    # build output directories
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    
    # Load the DICOM file
    dicom_data = pydicom.dcmread(dicom_directory)
    
    # Build and save patient pseudo and local identifier database
    pseudo_id, local_id = _select_identifier(dicom_data, identifier, local_id_excel_path)
    
    # Build and save metadata dictionary and database
    _get_and_save_metadata(dicom_data, fields_to_keep, local_id, output_directory, metadata_excel_path)
    
    # Save DICOM files as Nifti
    dicom_directory = os.path.dirname(dicom_directory)
    output_filename = os.path.join(output_directory, 'image.nii.gz')
    dicom2nifti.dicom_series_to_nifti(dicom_directory, output_filename)
    new_output_directory = os.path.join(os.path.dirname(output_directory), str(local_id))
    os.rename(output_directory, new_output_directory)

def _4D_extract_image_and_metadata(dicom_directory: str, output_directory: str, identifier: str, fields_to_keep: dict, time_stamp_keyword: str, metadata_excel_path: str, local_id_excel_path: str, allow_4D: bool = ALLOW_4D, show_progress: bool = True) -> None:
    """
    Extract 4D images and metadata for each DICOM folder.

    Inputs:
        - dicom_directory: str = absolute path to DICOM directory
        - output_directory: str = absolute path to ouptut directory
        - identifier: str = DICOM keyword to be used as identifier
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - time_stamp_keyword: str = DICOM keyword to be used for 4D data reconstruction (can be None)
        - metadata_excel_path: str = absolute path to Excel file containing metadata table
        - local_id_excel_path: str = absolute path to Excel file containing linking table
        - allow_4D: bool = whether or not to allow 4D extraction (default = ALLOW_4D)
        - show_progress: bool = whether or not to print progress (default = True)
    """

    # if sitk not available, 4D extraction cannot be done
    if not allow_4D:
        raise Exception("4D extraction not available because SimpleITK is not installed.")
        
    # build output directories
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    temp_folder = os.path.join(os.path.dirname(output_directory), 'temp')
    os.makedirs(temp_folder)
    
    # get one dicom file
    dicom_data = pydicom.dcmread(dicom_directory)
    
    # try block to allow for finally: shutil.rmtree(temp_folder)
    try:
        
        # organize directory in temp folder according to time stamp keyword
        time_stamps = _4D_get_and_organize_time_stamps(dicom_directory, time_stamp_keyword, temp_folder)
        
        # build and save patient pseudo and local identifier database
        pseudo_id, local_id = _select_identifier(dicom_data, identifier, local_id_excel_path)
        
        # build and save metadata dictionary and database
        _get_and_save_metadata(dicom_data, fields_to_keep, local_id, output_directory, metadata_excel_path)
    
        # save time stamps dictionary
        sorted_time_stamps = _4D_save_time_stamps(time_stamps, output_directory)

        # save DICOM files as Nifti for each timestamp
        for i, time_stamp in enumerate(sorted_time_stamps):
            output_filename = os.path.join(output_directory, str(i) + '.nii.gz')
            if show_progress:
                print(f"Image {i+1}/{len(sorted_time_stamps)}")

            reader = sitk.ImageSeriesReader()
            time_stamp_files = os.path.join(temp_folder, time_stamp)
            dicom_names = reader.GetGDCMSeriesFileNames(time_stamp_files)
            reader.SetFileNames(dicom_names)
            image = reader.Execute()
            sitk.WriteImage(image, output_filename)
                
    # always remove temporary directory
    finally:
        shutil.rmtree(temp_folder)

def extraction(input_root: str, output_root: str, profile: int, identifier: str, time_stamp: str, progress_bar: bool = PROGRESS_BAR) -> None:
    """
    Main function to extract NifTi files from a DICOM directory.

    Inputs:
        - input_root: str = absolute path to root of all DICOM folders
        - output_root: str = absolute path to output folder
        - profile: int = number corresponding to profile to be selected
        - identifier: str = DICOM keyword to be used as identifier
        - time_stamp: str = DICOM keyword to be used for 4D data reconstruction (can be None)
        - progress_bar: bool = (default = PROGRESS_BAR)
    """

    # build output directories
    if not os.path.exists(output_root):
        os.makedirs(output_root)
    metadata_excel_path = os.path.join(output_root, 'metadata.xlsx')
    local_id_excel_path = os.path.join(output_root, 'local_table.xlsx')
    
    # overview of files and progress bar
    walk = os.walk(input_root)
    if progress_bar:
        walk = tqdm(os.walk(input_root), total=len(list(os.walk(input_root))))
    else:
        print("Extraction...")
        
    # get all the field to keep
    fields_to_keep = _select_profile(profile)

    # explore all folders
    for root, dirs, files in walk:

        # get .dcm files
        dcm_files = [file for file in files if file.lower().endswith('.dcm')]

        # if .dcm files are available
        if len(dcm_files) > 1:
            
            # create output folder
            rel_folder_path = os.path.relpath(root, input_root)
            output_directory = os.path.join(output_root, rel_folder_path)
            os.makedirs(output_directory, exist_ok=True)
            dicom_directory = os.path.join(root, dcm_files[0])
            
            # extraction
            if profile == 3:
                _4D_extract_image_and_metadata(dicom_directory, output_directory, identifier, fields_to_keep, time_stamp, metadata_excel_path, local_id_excel_path)
            else:
                _extract_image_and_metadata(dicom_directory, output_directory, identifier, fields_to_keep, metadata_excel_path, local_id_excel_path)
                
    print("Extraction done.")
    print(" =>", output_root)
        

""" MAIN """

def main():
    # Parser
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help='Absolute path to the root folder containing DICOM files.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Absolute path to output folder where to save pseudonymized nifti files.')
    parser.add_argument('--profile', '-p', type=int, default=1, help='Selected profile (0: user-defined, 1: pseudonymization, 2: pseudomymization + keep study time, 3: anonymization 4D).')
    parser.add_argument('--identifier', '-i', type=str, default='PatientID', help='Identifier to be used for linking table (PatientID, StudyID, AgfaID).')
    parser.add_argument('--timestamp', '-t', type=str, default=None, help='DICOM keyword to be used for time stamp.')
    args = parser.parse_args()
    
    # Input root
    input_root = args.input
    
    # Output root
    output_root = args.output
    if output_root is None:
        output_root = input_root + '_extracted'
        
    # Profile
    profile = args.profile
    
    # Identifier
    identifier = args.identifier
    
    # Time stamp
    time_stamp = args.timestamp
    
    # Extraction
    extraction(input_root, output_root, profile, identifier, time_stamp)

# python extraction.py INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -t TIMESTAMP

if __name__ == '__main__':

    main()

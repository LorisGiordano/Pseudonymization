"""
Discovery of the DICOM files of an input (detected by content) and grouping by series.
"""

""" IMPORTS """

# Pre-installed packages
import os
from collections import defaultdict

# Pydicom
import pydicom
from pydicom.uid import MediaStorageDirectoryStorage


""" FUNCTIONS """

def is_dicom_file(path: str) -> bool:
    """
    Check whether a file is a DICOM file based on its content (not its extension): files with the 'DICM'
    prefix after the 128-byte preamble (also if damaged, so that they are reported as failed), or '.dcm' files
    without preamble that pydicom can read as a dataset with a SOP Class UID. DICOMDIR files (media storage
    directories) are not considered as DICOM images.

    Inputs:
        - path: str = path to file

    Outputs:
        - is_dicom: bool = whether the file is a DICOM file to process
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

def find_dicom_files(input_folder: str, single_file: str = None) -> list[str]:
    """
    Find all DICOM files of an input folder (recursively, folders in os.walk order, files sorted by name), or the
    single input file. Other files (e.g. README, DICOMDIR) are ignored.

    Inputs:
        - input_folder: str = path to input folder (folder of the file for a single input file)
        - single_file: str = file name of the single input file (default = None => all files of the folder)

    Outputs:
        - dicom_files: list[str] = paths to the DICOM files
    """

    if single_file:
        return [os.path.join(input_folder, single_file)]
    return [os.path.join(root, file) for root, dirs, files in os.walk(input_folder) for file in sorted(files)
            if is_dicom_file(os.path.join(root, file))]

def group_by_series(dicom_files: list[str]) -> dict:
    """
    Group DICOM files by series (a folder can contain several series, a series can be split over folders).

    Inputs:
        - dicom_files: list[str] = paths to DICOM files

    Outputs:
        - series: dict = SeriesInstanceUID (keys) and list of (path, dataset without pixel data) sorted by
                         InstanceNumber (values)
    """

    series = defaultdict(list)
    for path in dicom_files:
        dicom_data = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        series[str(dicom_data.get('SeriesInstanceUID', ''))].append((path, dicom_data))
    for files in series.values():
        files.sort(key=lambda item: int(item[1].get('InstanceNumber', 0) or 0))
    return series

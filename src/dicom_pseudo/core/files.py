"""
Discovery of the DICOM files of an input (detected by content), grouping by series, and saving of DICOM files.
"""

""" IMPORTS """

# Pre-installed packages
import os
import glob
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

def iter_dicom_folders(input_folder: str, single_file: str = None):
    """
    Iterate over the folders of an input containing DICOM files, one folder at a time (folders in os.walk order, files
    sorted by name), without listing all the files of the input in memory (for huge datasets).

    Inputs:
        - input_folder: str = path to input folder (folder of the file for a single input file)
        - single_file: str = file name of the single input file (default = None => all folders of the input)

    Outputs (generator):
        - folder: str = relative folder ('.' for the input folder itself)
        - dicom_files: list[str] = paths to the DICOM files of the folder
    """

    if single_file:
        yield '.', [os.path.join(input_folder, single_file)]
        return
    for root, dirs, files in os.walk(input_folder):
        dicom_files = [os.path.join(root, file) for file in sorted(files) if is_dicom_file(os.path.join(root, file))]
        if dicom_files:
            yield os.path.relpath(root, input_folder), dicom_files

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

def save_dicom(dicom_data: pydicom.dataset.FileDataset, output_path: str) -> None:
    """
    Save a DICOM file in standard DICOM file format (preamble, prefix and file meta information). The file is written
    atomically: first to a temporary file in the same folder, then renamed, so that an interrupted process never
    leaves a partially written file.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object
        - output_path: str = path to output file (folders are created if needed)
    """

    folder = os.path.dirname(output_path)
    os.makedirs(folder, exist_ok=True)
    temporary_path = os.path.join(folder, f'.{os.path.basename(output_path)}.tmp-{os.getpid()}')
    try:
        if int(pydicom.__version__.split('.')[0]) >= 3:
            dicom_data.save_as(temporary_path, enforce_file_format=True)
        else:
            dicom_data.save_as(temporary_path, write_like_original=False)
        os.replace(temporary_path, output_path)
        for stale_path in glob.glob(os.path.join(glob.escape(folder), f'.{glob.escape(os.path.basename(output_path))}.tmp-*')):
            os.remove(stale_path)                        # left by an interrupted process writing the same file earlier
    except BaseException:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise

"""
Conversion of the images of a series to NifTi: 3D/4D volumes with dicom2nifti, 2D images with a writer following the
dicom2nifti conversion.
"""

""" IMPORTS """

# Pre-installed packages
import os
import json
import shutil
import tempfile

# Pydicom
import pydicom

# Dicom2nifti (its warnings are not shown, conversion errors are reported per series)
import logging
import dicom2nifti
from dicom2nifti import common as dicom2nifti_common, image_reorientation
from dicom2nifti.convert_generic import create_rgba_nifti
logging.getLogger('dicom2nifti').setLevel(logging.ERROR)

# Nibabel
import nibabel

# Extraction modules
from .timepoints import spatial_position, time_positions, sort_labels


""" CONVERSION """

def convert_volume(paths: list[str], output_file: str) -> None:
    """
    Convert DICOM files (one 3D volume) to NifTi with dicom2nifti, using a temporary folder containing only these files.

    Inputs:
        - paths: list[str] = paths to the DICOM files of the volume
        - output_file: str = path to output NifTi file
    """

    temp_folder = tempfile.mkdtemp()
    try:
        for i, path in enumerate(paths):
            shutil.copyfile(path, os.path.join(temp_folder, f'{i:06d}.dcm'))
        dicom2nifti.dicom_series_to_nifti(temp_folder, output_file)
    finally:
        shutil.rmtree(temp_folder, ignore_errors=True)

def is_2d(files: list) -> bool:
    """
    Check whether a series consists of 2D images that do not form a volume: single-frame images all at the same
    spatial position, or without spatial position (e.g. projection radiography CR/DX/MG, localizers, repeated slices).

    Inputs:
        - files: list = (path, dataset) of the series

    Outputs:
        - is_2d: bool = whether the series consists of 2D images
    """

    if any(int(dicom_data.get('NumberOfFrames', 1) or 1) > 1 for _, dicom_data in files):
        return False
    return len({spatial_position(dicom_data) for _, dicom_data in files}) <= 1

def convert_2d(path: str, output_file: str) -> None:
    """
    Convert a single-frame 2D DICOM image to NifTi, following the dicom2nifti conversion (same pixel data scaling,
    affine, data orientation and header), as dicom2nifti only converts volumes:
        - pixel data with modality LUT (rescale slope/intercept) applied, stored as x, y, 1 (RGB as RGBA)
        - affine from ImageOrientationPatient, ImagePositionPatient and PixelSpacing (slice thickness as 3rd dimension);
          for images without patient coordinates (projection radiography), the image plane is placed at the origin
          with PixelSpacing (or ImagerPixelSpacing, at the detector) as pixel size
        - TR/TE, scaling and units in the header, data reoriented to LAS as dicom2nifti does

    Inputs:
        - path: str = path to DICOM file
        - output_file: str = path to output NifTi file
    """

    dicom_data = pydicom.dcmread(path)
    if int(dicom_data.get('SamplesPerPixel', 1) or 1) == 3 and dicom_data.PhotometricInterpretation != 'RGB':
        raise ValueError(f"2D color images with photometric interpretation {dicom_data.PhotometricInterpretation} not supported")

    # pixel data (as dicom2nifti)
    data = dicom2nifti_common.get_volume_pixeldata([dicom_data])

    # geometry: patient coordinates if available, otherwise image plane at the origin
    if all(keyword in dicom_data for keyword in ('ImageOrientationPatient', 'ImagePositionPatient', 'PixelSpacing')):
        geometry = dicom_data
    else:
        geometry = pydicom.Dataset()
        geometry.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        geometry.ImagePositionPatient = [0, 0, 0]
        geometry.PixelSpacing = dicom_data.get('PixelSpacing', None) or dicom_data.get('ImagerPixelSpacing', None) or [1, 1]
    affine, _ = dicom2nifti_common.create_affine([geometry])

    # NifTi image and header (as dicom2nifti)
    if dicom_data.get('PhotometricInterpretation', '') == 'RGB':
        nifti_image = create_rgba_nifti(data, affine)
    else:
        nifti_image = nibabel.Nifti1Image(data, affine)
    if 'RepetitionTime' in dicom_data and 'EchoTime' in dicom_data:
        dicom2nifti_common.set_tr_te(nifti_image, dicom_data.RepetitionTime, dicom_data.EchoTime)
    nifti_image.header.set_slope_inter(1, 0)
    nifti_image.header.set_xyzt_units(2)
    nifti_image.to_filename(output_file)
    image_reorientation.reorient_image(nifti_image, output_file)


""" SERIES """

def write_nifti(files: list, output_directory: str, four_d: bool = False, time_stamp_keyword: str = None) -> dict:
    """
    Write the images of a series as NifTi:
        - 4D (if requested and a temporal dimension is found): <time point>.nii.gz and timestamps.json
        - 3D: image.nii.gz
        - 2D images that do not form a volume: image.nii.gz (single image) or image_<index>.nii.gz (several images,
          InstanceNumber order)

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - output_directory: str = path to output folder of the series
        - four_d: bool = whether to reconstruct 4D data (default = False)
        - time_stamp_keyword: str = DICOM keyword to be used for 4D data reconstruction (default = None => automatic)

    Outputs:
        - information: dict = information on the written NifTi (stored in the overview table metadata.xlsx)
    """

    paths = [path for path, _ in files]
    keyword, labels = time_positions(files, time_stamp_keyword) if four_d else (None, None)

    # 4D: one NifTi per time point
    if keyword is not None:
        sorted_labels = sort_labels(set(labels))
        for index, label in enumerate(sorted_labels):
            convert_volume([path for path, file_label in zip(paths, labels) if file_label == label], os.path.join(output_directory, f'{index}.nii.gz'))
        with open(os.path.join(output_directory, 'timestamps.json'), 'w') as file:
            json.dump({'keyword': keyword, 'timestamps': dict(enumerate(sorted_labels))}, file, indent=4)
        image_type, number_of_nifti, time_points = '4D', len(sorted_labels), len(sorted_labels)

    # 3D volume, or 2D images (not a volume) if dicom2nifti cannot convert the series
    else:
        time_points = 0
        try:
            convert_volume(paths, os.path.join(output_directory, 'image.nii.gz'))
            image_type, number_of_nifti = '3D', 1
        except Exception:
            if not is_2d(files):
                raise
            if len(paths) == 1:
                convert_2d(paths[0], os.path.join(output_directory, 'image.nii.gz'))
            else:
                for index, path in enumerate(paths):
                    convert_2d(path, os.path.join(output_directory, f'image_{index}.nii.gz'))
            image_type, number_of_nifti = '2D', len(paths)

    return {
        'NIfTI': image_type,
        'Number of NIfTI files': number_of_nifti,
        'Time points': time_points,
        'Time keyword': keyword or '',
    }

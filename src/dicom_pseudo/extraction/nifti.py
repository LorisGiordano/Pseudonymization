"""
Conversion of the images of a series to NifTi: 3D/4D volumes with dicom2nifti, 2D images with a writer following the
dicom2nifti conversion.
"""

""" IMPORTS """

# Pre-installed packages
import io
import os
import json
import contextlib
import shutil
import tempfile

# Numpy
import numpy

# Pydicom
import pydicom

# Dicom2nifti (its warnings are not shown, conversion errors are reported per series)
import logging
import dicom2nifti
from dicom2nifti import common as dicom2nifti_common, image_reorientation
from dicom2nifti.convert_generic import create_rgba_nifti
from dicom2nifti.exceptions import ConversionValidationError
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
        # numerical warnings and tracebacks printed by dicom2nifti (e.g. division by zero for images at the same
        # position) are not shown, conversion errors are reported per series
        with numpy.errstate(divide='ignore', invalid='ignore'), contextlib.redirect_stderr(io.StringIO()):
            dicom2nifti.dicom_series_to_nifti(temp_folder, output_file)
    finally:
        shutil.rmtree(temp_folder, ignore_errors=True)

def is_2d(files: list, error: Exception) -> bool:
    """
    Check whether a series that dicom2nifti cannot convert as a volume consists of 2D images, to be converted one by one:
        - single-frame images without slice geometry (no ImageOrientationPatient, e.g. projection radiography CR/DX/MG)
        - single-frame images rejected by dicom2nifti as too few slices or localizers (e.g. single slices, localizers)
    Other series (e.g. images that need information missing in the files, such as mosaic images) are not 2D images.

    Inputs:
        - files: list = (path, dataset) of the series
        - error: Exception = error of the dicom2nifti conversion of the series

    Outputs:
        - is_2d: bool = whether the series consists of 2D images
    """

    if any(int(dicom_data.get('NumberOfFrames', 1) or 1) > 1 for _, dicom_data in files):
        return False
    no_geometry = all('ImageOrientationPatient' not in dicom_data for _, dicom_data in files)
    too_few_slices = isinstance(error, ConversionValidationError) and 'TOO_FEW_SLICES' in str(error)
    return no_geometry or too_few_slices

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

def write_nifti(files: list, output_directory: str, time_stamp_keyword: str = None) -> dict:
    """
    Write the images of a series as NifTi:
        - diffusion series (b-values found by dicom2nifti): image.nii.gz (4D), image.bval and image.bvec
        - 4D series (several images at each slice position) with time points found in the files (see
          timepoints.time_positions): <time point>.nii.gz and timestamps.json
        - 3D: image.nii.gz
        - 2D images that do not form a volume: image.nii.gz (single image) or image_<index>.nii.gz (several images,
          InstanceNumber order)
    A 4D series without time points in the files (e.g. time fields removed by the pseudonymization profile) is not
    written (error).

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - output_directory: str = path to output folder of the series
        - time_stamp_keyword: str = DICOM keyword to be used for the time points of 4D series (default = None =>
                                    automatic detection)

    Outputs:
        - information: dict = information on the written NifTi (stored in the overview table metadata.xlsx)
    """

    paths = [path for path, _ in files]
    keyword, labels = time_positions(files, time_stamp_keyword)
    image_file = os.path.join(output_directory, 'image.nii.gz')

    # whole series with dicom2nifti (3D volume, or 4D series that dicom2nifti recognises, e.g. diffusion)
    try:
        convert_volume(paths, image_file)
        error = None
    except Exception as conversion_error:
        error = conversion_error
    if error is None and os.path.exists(os.path.join(output_directory, 'image.bval')):
        return {'NIfTI': '4D', 'Number of NIfTI files': 1, 'Time points': nibabel.load(image_file).shape[-1], 'Time keyword': ''}

    # 4D: one NifTi per time point
    if keyword is not None:
        if os.path.exists(image_file):
            os.remove(image_file)
        sorted_labels = sort_labels(set(labels))
        for index, label in enumerate(sorted_labels):
            convert_volume([path for path, file_label in zip(paths, labels) if file_label == label], os.path.join(output_directory, f'{index}.nii.gz'))
        with open(os.path.join(output_directory, 'timestamps.json'), 'w') as file:
            json.dump({'keyword': keyword, 'timestamps': dict(enumerate(sorted_labels))}, file, indent=4)
        return {'NIfTI': '4D', 'Number of NIfTI files': len(sorted_labels), 'Time points': len(sorted_labels), 'Time keyword': keyword}

    # 4D without time points: not written
    no_time = ValueError('4D series without time points in the files (time fields missing, e.g. removed by the '
                         'pseudonymization profile: use profile 3 or 5 to keep them)')
    if error is None and len(nibabel.load(image_file).shape) == 4:
        os.remove(image_file)
        raise no_time
    if error is not None and not is_2d(files, error):
        positions = [spatial_position(dicom_data) for _, dicom_data in files]
        if all(positions) and len(set(positions)) < len(positions):
            raise no_time from error
        raise error

    # 3D volume, or 2D images (not a volume) if dicom2nifti cannot convert the series
    if error is None:
        image_type, number_of_nifti = '3D', 1
    else:
        if len(paths) == 1:
            convert_2d(paths[0], image_file)
        else:
            for index, path in enumerate(paths):
                convert_2d(path, os.path.join(output_directory, f'image_{index}.nii.gz'))
        image_type, number_of_nifti = '2D', len(paths)

    return {'NIfTI': image_type, 'Number of NIfTI files': number_of_nifti, 'Time points': 0, 'Time keyword': ''}

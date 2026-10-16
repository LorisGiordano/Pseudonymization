"""
Test data (built from the DICOM files bundled with pydicom, no download needed) and analysis helpers.

The analysis helpers never return original values, only counts and field names, so that test reports on real data
do not disclose identifiers.
"""

import collections
import glob
import os
import shutil

import numpy as np
import pydicom
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
from pydicom.uid import UID_dictionary, generate_uid

from dicom_pseudo.core.pseudonym import remap_uid


""" TEST DATA """

PYDICOM_DATA = os.path.dirname(get_testdata_file('CT_small.dcm'))
DICOMDIR_TESTS = os.path.join(PYDICOM_DATA, 'dicomdirtests')


def _save(ds: Dataset, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.save_as(path, enforce_file_format=True)


def ct_volume(folder: str, patient: str, name: str, study_uid: str, series_uid: str = None, slices: int = 8, series_number: int = 1,
              time_points: int = 1, files: list = None) -> list[str]:
    """
    Synthetic CT series built from CT_small: `slices` axial slices 2 mm apart, `time_points` volumes (4D: temporal
    positions and content times, no repetition and echo times as in CT perfusion). Returns the written paths. `files` selects the slice indices written to this folder
    (to split a series over folders).
    """

    base = pydicom.dcmread(get_testdata_file('CT_small.dcm'))
    series_uid = series_uid or generate_uid()
    frame_of_reference = generate_uid(entropy_srcs=[study_uid])
    paths, first_instance = [], None
    for t in range(time_points):
        for i in range(slices):
            index = t * slices + i
            if files is not None and index not in files:
                continue
            ds = base.copy()
            ds.PatientID, ds.PatientName = patient, name
            ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = study_uid, series_uid, generate_uid()
            ds.FrameOfReferenceUID = frame_of_reference
            ds.SeriesNumber, ds.InstanceNumber = series_number, index + 1
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [-60.0, -60.0, 2.0 * i]
            ds.SliceLocation, ds.SliceThickness = 2.0 * i, 2.0
            ds.PixelData = (base.pixel_array + (index % 50)).astype(base.pixel_array.dtype).tobytes()
            if time_points > 1:
                ds.TemporalPositionIdentifier, ds.NumberOfTemporalPositions = t + 1, time_points
                ds.ContentTime = f'1200{t:02d}.000000'
            # reference to the first instance of the series (as e.g. localizer references)
            if first_instance is None:
                first_instance = ds.SOPInstanceUID
            else:
                reference = Dataset()
                reference.ReferencedSOPClassUID, reference.ReferencedSOPInstanceUID = ds.SOPClassUID, first_instance
                ds.ReferencedImageSequence = [reference]
            path = os.path.join(folder, f'slice_{index:03d}.dcm')
            _save(ds, path)
            paths.append(path)
    return paths


def build_tree(root: str) -> str:
    """
    Test input tree (about 110 files):
        - cohort/: pydicom dicomdirtests (2 patients, several studies and series, folders with several series), .dcm added
        - noext/: series without file extension (and without pixel data)
        - single/: folder with one file (CT_small)
        - with space/: path with a space (2 MR_small images)
        - agfa/: empty AccessionNumber, AGFA private identifier (7fdd,1013), PatientSizeCodeSequence, OtherPatientIDsSequence
        - overlay/: MR image with an overlay plane (group 6000)
        - volume/: synthetic CT volume (8 slices)
        - split/part0, split/part1: one series split over two folders
        - multi/: two series in one folder
        - fourd/: synthetic 4D CT (3 time points x 6 slices)
        - projection/: projection image without slice geometry (DX)
    """

    # pydicom dicomdirtests cohort (.dcm extension added) and extensionless series
    for patient in ('77654033', '98892001', '98892003'):
        for folder, _, files in os.walk(os.path.join(DICOMDIR_TESTS, patient)):
            for file in files:
                target = os.path.join(root, 'cohort', os.path.relpath(folder, DICOMDIR_TESTS))
                os.makedirs(target, exist_ok=True)
                shutil.copy(os.path.join(folder, file), os.path.join(target, file + '.dcm'))
    shutil.copytree(os.path.join(DICOMDIR_TESTS, 'TINY_ALPHA', 'PT000000', 'ST000000', 'SE000000'), os.path.join(root, 'noext', 'SE000000'))

    # single file, path with a space
    os.makedirs(os.path.join(root, 'single'))
    shutil.copy(get_testdata_file('CT_small.dcm'), os.path.join(root, 'single', 'CT_small.dcm'))
    for i in range(2):
        ds = pydicom.dcmread(get_testdata_file('MR_small.dcm'))
        ds.SOPInstanceUID, ds.InstanceNumber = generate_uid(), i + 1
        _save(ds, os.path.join(root, 'with space', f'mr{i}.dcm'))

    # AGFA private identifier, kept sequence, nested identifiers
    for i in range(2):
        ds = pydicom.dcmread(get_testdata_file('CT_small.dcm'))
        ds.SOPInstanceUID, ds.InstanceNumber = generate_uid(), i + 1
        ds.AccessionNumber = ''
        ds.add_new(0x7fdd0010, 'LO', 'AGFA')
        ds.add_new(0x7fdd1013, 'LO', 'AGFA-ACC-778899')
        ds.PatientSizeCodeSequence = [Dataset()]
        ds.PatientSizeCodeSequence[0].CodeValue, ds.PatientSizeCodeSequence[0].CodeMeaning = 'L', 'Large'
        _save(ds, os.path.join(root, 'agfa', f'ct{i}.dcm'))

    # overlay plane
    ds = pydicom.dcmread(get_testdata_file('MR_small.dcm'))
    ds.SOPInstanceUID = generate_uid()
    ds.add_new(0x60000010, 'US', ds.Rows)
    ds.add_new(0x60000011, 'US', ds.Columns)
    ds.add_new(0x60000040, 'CS', 'G')
    ds.add_new(0x60000050, 'SS', [1, 1])
    ds.add_new(0x60000100, 'US', 1)
    ds.add_new(0x60000102, 'US', 0)
    ds.add_new(0x60003000, 'OW', bytes(ds.Rows * ds.Columns // 8))
    _save(ds, os.path.join(root, 'overlay', 'ov.dcm'))

    # synthetic volumes: 3D, series split over two folders, two series in one folder, 4D
    study = generate_uid()
    ct_volume(os.path.join(root, 'volume'), 'VOL0001', 'VOLUME^PATIENT', study, series_number=1)
    split_series = generate_uid()
    ct_volume(os.path.join(root, 'split', 'part0'), 'VOL0001', 'VOLUME^PATIENT', study, split_series, series_number=2, files=[0, 2, 4, 6])
    ct_volume(os.path.join(root, 'split', 'part1'), 'VOL0001', 'VOLUME^PATIENT', study, split_series, series_number=2, files=[1, 3, 5, 7])
    ct_volume(os.path.join(root, 'multi'), 'VOL0002', 'MULTI^PATIENT', generate_uid(), series_number=3, slices=6)
    multi = pydicom.dcmread(sorted(glob.glob(os.path.join(root, 'multi', '*.dcm')))[0]).StudyInstanceUID
    for path in ct_volume(os.path.join(root, 'multi_tmp'), 'VOL0002', 'MULTI^PATIENT', multi, series_number=4, slices=6):
        shutil.move(path, os.path.join(root, 'multi', 'b_' + os.path.basename(path)))
    os.rmdir(os.path.join(root, 'multi_tmp'))
    ct_volume(os.path.join(root, 'fourd'), 'VOL0003', 'FOURD^PATIENT', generate_uid(), slices=6, time_points=3, series_number=5)

    # projection image without slice geometry
    ds = pydicom.dcmread(get_testdata_file('CT_small.dcm'))
    for keyword in ('ImageOrientationPatient', 'ImagePositionPatient', 'PixelSpacing', 'SliceLocation'):
        delattr(ds, keyword)
    ds.Modality, ds.SOPClassUID = 'DX', '1.2.840.10008.5.1.4.1.1.1.1'
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.ImagerPixelSpacing = [0.2, 0.2]
    ds.SOPInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    _save(ds, os.path.join(root, 'projection', 'dx.dcm'))
    return root


def build_edge_tree(root: str) -> str:
    """
    Edge cases: DICOMDIR, non-DICOM files, text file named .dcm, damaged DICOM file, DICOM file without preamble,
    and the same instance (SOPInstanceUID) in two folders.
    """

    os.makedirs(os.path.join(root, 'series'))
    shutil.copy(os.path.join(DICOMDIR_TESTS, 'DICOMDIR'), os.path.join(root, 'series', 'DICOMDIR'))
    shutil.copy(get_testdata_file('CT_small.dcm'), os.path.join(root, 'series', 'ok.dcm'))
    ds = pydicom.dcmread(get_testdata_file('MR_small.dcm'))
    ds.preamble, ds.file_meta = None, pydicom.dataset.FileMetaDataset()
    pydicom.dcmwrite(os.path.join(root, 'series', 'nopreamble.dcm'), ds, enforce_file_format=False, implicit_vr=True, little_endian=True)
    data = open(get_testdata_file('CT_small.dcm'), 'rb').read()
    open(os.path.join(root, 'series', 'broken.dcm'), 'wb').write(data[:132] + b'\x02\x00\x10\x00UI\xff\xff' + b'garbage' * 10)
    open(os.path.join(root, 'series', 'notes.dcm'), 'w').write('not a DICOM file')
    open(os.path.join(root, 'series', 'README.txt'), 'w').write('Patient: DOE^JOHN')
    os.makedirs(os.path.join(root, 'copy'))
    shutil.copy(get_testdata_file('CT_small.dcm'), os.path.join(root, 'copy', 'duplicate.dcm'))
    return root


""" ANALYSIS (counts and field names only, never values) """

SENSITIVE_KEYWORDS = {'PatientID', 'PatientName', 'OtherPatientIDs', 'AccessionNumber', 'PatientBirthDate', 'InstitutionName',
                      'InstitutionAddress', 'InstitutionalDepartmentName', 'ReferringPhysicianName', 'PerformingPhysicianName',
                      'OperatorsName', 'StationName', 'DeviceSerialNumber', 'StudyID', 'StudyDescription', 'SeriesDescription',
                      'ProtocolName', 'RequestingPhysician', 'PatientAddress', 'PatientTelephoneNumbers'}


def is_dicom(path: str) -> bool:
    """DICOM file detected by content: DICM prefix, or .dcm dataset with a SOP Class UID."""
    try:
        with open(path, 'rb') as file:
            file.seek(128)
            if file.read(4) == b'DICM':
                return True
        return path.endswith('.dcm') and 'SOPClassUID' in pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return False


def read_inputs(root: str) -> dict:
    """Valid DICOM inputs of a tree: relative path -> dataset (DICOMDIR and damaged files excluded)."""
    inputs = {}
    for path in glob.glob(os.path.join(root, '**', '*'), recursive=True):
        if os.path.isfile(path) and is_dicom(path):
            try:
                ds = pydicom.dcmread(path, force=True)
            except Exception:
                continue
            if 'SOPClassUID' in ds and 'SOPInstanceUID' in ds:
                inputs[os.path.relpath(path, root)] = ds
    return inputs


def output_map(inputs: dict, output_root: str, key: bytes, linkage: str = 'patient') -> dict:
    """Input relative path -> pseudonymized output path (matched through the pseudonymized SOPInstanceUID)."""
    by_uid = {remap_uid(str(ds.SOPInstanceUID), key, str(ds.get('StudyInstanceUID', '')) if linkage == 'study' else ''): path
              for path, ds in inputs.items()}
    result = {}
    for path in glob.glob(os.path.join(output_root, '**', '*.dcm'), recursive=True):
        uid = os.path.splitext(os.path.basename(path))[0]
        if uid in by_uid:
            result[by_uid[uid]] = path
    return result


def sensitive_tokens(ds: Dataset) -> dict:
    """Identifying original values of a dataset: value -> field name (names, IDs, dates, times, private text...)."""
    tokens = {}
    for elem in list(ds.file_meta.iterall()) + list(ds.iterall()):
        if elem.VR in ('SQ', 'OB', 'OW', 'UN', 'OF', 'OD', 'UI') or elem.value in (None, '', b''):
            continue
        if elem.VR in ('PN', 'DA', 'DT', 'TM', 'AE') or elem.keyword in SENSITIVE_KEYWORDS or (elem.tag.is_private and elem.VR in ('LO', 'SH', 'LT', 'ST')):
            value = str(elem.value).strip()
            if len(value) >= 3 and set(value) - set('0.: '):
                tokens[value] = elem.keyword or str(elem.tag)
    return tokens


def surviving_values(raw: Dataset, out: Dataset, kept_tags: set, kept_groups: set) -> collections.Counter:
    """Original identifying values found in a pseudonymized dataset outside the kept fields: Counter of field names."""
    tokens = sensitive_tokens(raw)
    found = collections.Counter()
    for elem in list(out.file_meta.iterall()) + list(out.iterall()):
        if elem.tag in kept_tags or elem.tag.group in kept_groups or elem.tag.is_private_creator or elem.VR in ('SQ', 'UI') or elem.value in (None, '', b''):
            continue
        value = str(elem.value).strip()
        if value in tokens:
            found[f'{tokens[value]} -> {elem.keyword or elem.tag}'] += 1
    return found


def original_uids(ds: Dataset) -> set:
    """Original instance UIDs of a dataset (standard UIDs excluded)."""
    return {str(elem.value) for elem in ds.iterall() if elem.VR == 'UI' and elem.value and str(elem.value) not in UID_dictionary and len(str(elem.value)) > 10}


def nifti_files(folder: str) -> list[str]:
    """NIfTI files of an output folder, in natural order (image_2 before image_10)."""
    import re
    return sorted(glob.glob(os.path.join(folder, '*.nii.gz')), key=lambda f: [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', os.path.basename(f))])


def same_nifti(folder_a: str, folder_b: str) -> bool:
    """Whether two output folders hold the same NIfTI images (voxels, affine)."""
    import nibabel
    a, b = nifti_files(folder_a), nifti_files(folder_b)
    if not a or len(a) != len(b):
        return False
    for x, y in zip(a, b):
        image_x, image_y = nibabel.load(x), nibabel.load(y)
        if image_x.shape != image_y.shape or not np.array_equal(image_x.get_fdata(), image_y.get_fdata()) or not np.allclose(image_x.affine, image_y.affine):
            return False
    return True

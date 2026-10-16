"""Extraction to NIfTI: input structure reproduced, 2D/3D/4D series, same images from raw and pseudonymized data."""

import collections
import glob
import gzip
import json
import os

import nibabel
import pandas as pd
import pytest

from dicom_pseudo.core.files import find_dicom_files
from dicom_pseudo.core.tables import read_table
from dicom_pseudo.extraction import extraction
from dicom_pseudo.extraction.pipeline import group_by_folder_and_series

from helpers import same_nifti


@pytest.fixture(scope='module')
def extracted(tmp_path_factory):
    """Extract a folder (cached): extracted(input folder, profile) -> (output folder, overview table)."""
    cache = {}

    def run(input_root, profile=1, time_stamp=None):
        if (input_root, profile, time_stamp) not in cache:
            output = str(tmp_path_factory.mktemp(f'extracted_p{profile}'))
            extraction(input_root, output, profile, time_stamp, progress_bar=False)
            table = os.path.join(output, 'metadata.xlsx')    # not written when no series is extracted
            overview = read_table(table, dtype=str) if os.path.exists(table) else pd.DataFrame(columns=['Folder'])
            cache[(input_root, profile, time_stamp)] = (output, overview.set_index('Folder'))
        return cache[(input_root, profile, time_stamp)]

    return run


def test_input_structure_is_reproduced(tree, extracted):
    output, overview = extracted(tree)
    groups = group_by_folder_and_series(find_dicom_files(tree), tree)
    assert set(overview.index) <= set(groups)
    assert {folder for folder in groups if folder.startswith('multi')} == {'multi/3_CT', 'multi/4_CT'}, 'two series in one folder: one subfolder each'
    assert 'volume' in overview.index and 'split/part0' in overview.index, 'single-series folders are not renamed nor split'
    assert {os.path.relpath(os.path.dirname(p), output) for p in glob.glob(os.path.join(output, '**', '*.nii.gz'), recursive=True)} == set(overview.index)


def test_series_types(tree, extracted):
    output, overview = extracted(tree)
    assert overview.loc['volume', 'NIfTI'] == '3D' and nibabel.load(os.path.join(output, 'volume', 'image.nii.gz')).shape[2] == 8
    assert overview.loc['fourd', 'NIfTI'] == '4D' and overview.loc['fourd', 'Number of NIfTI files'] == '3'
    for folder in ('single', 'projection', 'overlay'):
        assert overview.loc[folder, 'NIfTI'] == '2D', folder
    projection = nibabel.load(os.path.join(output, 'projection', 'image.nii.gz'))
    assert projection.header.get_zooms()[:2] == pytest.approx((0.2, 0.2))
    assert 'noext/SE000000' not in overview.index, 'no pixel data: reported, not written'


@pytest.mark.parametrize('profile', [1, 3])
def test_four_d_time_points(tree, extracted, profile):
    """4D series: one NIfTI per time point, whatever the profile (the profile only selects the metadata)."""
    output, overview = extracted(tree, profile)
    assert overview.loc['fourd', 'NIfTI'] == '4D' and overview.loc['fourd', 'Time keyword'] == 'TemporalPositionIdentifier'
    assert sorted(os.listdir(os.path.join(output, 'fourd'))) == ['0.nii.gz', '1.nii.gz', '2.nii.gz', 'metadata.json', 'timestamps.json']
    assert json.load(open(os.path.join(output, 'fourd', 'timestamps.json')))['timestamps'] == {'0': '1', '1': '2', '2': '3'}
    assert overview.loc['volume', 'NIfTI'] == '3D', 'series without temporal dimension stay 3D'


@pytest.mark.parametrize('keyword, ok', [('NumberOfTemporalPositions', True), ('AcquisitionTime', False)])
def test_forced_time_stamp(tree, extracted, keyword, ok):
    output, overview = extracted(os.path.join(tree, 'fourd'), 1, keyword)
    assert ('.' in overview.index) == ok
    if ok:
        assert overview.loc['.', 'Time points'] == '3' and overview.loc['.', 'Time keyword'] == keyword


def test_forced_time_stamp_ignored_for_3d(tree, extracted):
    _, overview = extracted(os.path.join(tree, 'volume'), 1, 'AcquisitionTime')
    assert overview.loc['.', 'NIfTI'] == '3D'


def test_metadata(tree, extracted):
    output, overview = extracted(tree)
    metadata = json.load(open(os.path.join(output, 'single', 'metadata.json')))
    assert set(metadata) <= {'PatientAge', 'PatientSex', 'PatientWeight', 'PatientSize', 'PatientSizeCodeSequence', 'PatientBodyMassIndex'} and metadata
    assert {'Folder', 'Modality', 'NIfTI', 'Number of NIfTI files', 'Time points'} <= set(overview.reset_index().columns)


def test_rerun_is_idempotent(tree, tmp_path):
    output = str(tmp_path / 'out')
    for _ in range(2):
        extraction(os.path.join(tree, 'volume'), output, 1, progress_bar=False)
    assert len(read_table(os.path.join(output, 'metadata.xlsx'))) == 1


def test_same_images_from_pseudonymized_data(tree, inputs, pseudonymized, extracted):
    """
    Extraction from the pseudonymized files: same folders as the pseudonymized series, same images as from raw data,
    except 4D series, reported as their time fields are removed by profile 1.
    """
    pseudo, link_table = pseudonymized(1)
    raw_output, raw_overview = extracted(tree)
    pseudo_output, pseudo_overview = extracted(pseudo)
    series_folders = {os.path.relpath(os.path.dirname(p), pseudo) for p in glob.glob(os.path.join(pseudo, '**', '*.dcm'), recursive=True)}
    assert set(pseudo_overview.index) <= series_folders
    raw_folder = {}
    for folder, files in group_by_folder_and_series(find_dicom_files(tree), tree).items():
        raw_folder[(os.path.dirname(os.path.relpath(files[0][0], tree)), str(files[0][1].SeriesInstanceUID))] = folder
    table = read_table(link_table, dtype=str)
    split = table.groupby('Original SeriesInstanceUID')['Input folder'].nunique()
    compared = collections.Counter()
    for _, row in table.iterrows():
        if split[row['Original SeriesInstanceUID']] > 1:
            continue                                     # series split over input folders: merged by the pseudonymization
        raw = raw_folder[(row['Input folder'], row['Original SeriesInstanceUID'])]
        if raw not in raw_overview.index:
            assert row['Output folder'] not in pseudo_overview.index
            continue
        if raw_overview.loc[raw, 'NIfTI'] == '4D':
            assert row['Output folder'] not in pseudo_overview.index, raw
            compared['4D reported'] += 1
            continue
        assert same_nifti(os.path.join(raw_output, raw), os.path.join(pseudo_output, row['Output folder'])), raw
        compared[raw_overview.loc[raw, 'NIfTI']] += 1
    assert compared['3D'] and compared['2D'] and compared['4D reported']


def test_four_d_from_pseudonymized_data(tree, pseudonymized, extracted):
    pseudo, link_table = pseudonymized(3)
    folder = read_table(link_table, dtype=str).set_index('Input folder').loc['fourd', 'Output folder']
    raw_output, _ = extracted(tree, 3)
    pseudo_output, overview = extracted(pseudo, 3)
    assert overview.loc[folder, 'NIfTI'] == '4D'
    assert same_nifti(os.path.join(raw_output, 'fourd'), os.path.join(pseudo_output, folder))


def test_no_identifiers_in_extraction_of_pseudonymized_data(inputs, pseudonymized, extracted):
    pseudo, _ = pseudonymized(1)
    output, _ = extracted(pseudo)
    tokens = {str(ds.get(k, '')).strip() for ds in inputs.values() for k in ('PatientID', 'PatientName', 'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'InstitutionName')}
    tokens = {t for t in tokens if len(t) >= 4}
    found = 0
    for path in glob.glob(os.path.join(output, '**', '*'), recursive=True):
        if os.path.isfile(path):
            blob = gzip.open(path).read() if path.endswith('.gz') else (pd.read_excel(path).to_csv().encode() if path.endswith('.xlsx') else open(path, 'rb').read())
            found += sum(t.encode() in blob or t.encode() in os.path.relpath(path, output).encode() for t in tokens)
    assert found == 0

"""
Tests on real data: a sample of the series of the `_data/ibash_learners` dataset next to the repository (another dataset
can be given with the environment variable DICOM_PSEUDO_TEST_DATA). Skipped when the dataset is absent.

The sample (one or two series per manufacturer and image type, links with generic names) is pseudonymized with a new
test key. Assertion messages show counts and field names only, never original values. All derived data (links,
pseudonymized and extracted outputs) is written in a temporary folder deleted at the end of the module.
"""

import collections
import filecmp
import glob
import os
import pathlib
import tempfile

import pydicom
import pytest

from dicom_pseudo.core.files import find_dicom_files
from dicom_pseudo.core.pseudonym import load_key, remap_uid
from dicom_pseudo.core.settings import select_profile
from dicom_pseudo.core.tables import read_table
from dicom_pseudo.extraction import extraction
from dicom_pseudo.extraction.pipeline import group_by_folder_and_series
from dicom_pseudo.pseudonymization import pseudonymization

from helpers import is_dicom, original_uids, same_nifti, sensitive_tokens, surviving_values

DATA = os.environ.get('DICOM_PSEUDO_TEST_DATA',
                      os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, '_data', 'ibash_learners'))

pytestmark = [pytest.mark.real_data,
              pytest.mark.skipif(not os.path.isdir(DATA), reason=f'real dataset not found ({DATA})')]

MAX_FILES = 250          # largest series sampled
SERIES_PER_TYPE = 2      # sampled series per (manufacturer, mosaic, small/large series)

# fields that must never survive, whatever the profile (profile 5 included)
IDENTIFYING = {'PatientName', 'PatientID', 'OtherPatientIDs', 'PatientBirthDate', 'AccessionNumber', 'InstitutionName',
               'InstitutionAddress', 'InstitutionalDepartmentName', 'ReferringPhysicianName', 'PerformingPhysicianName',
               'OperatorsName', 'RequestingPhysician', 'PatientAddress', 'PatientTelephoneNumbers'}


def header_bytes(path: str) -> bytes:
    """Bytes of a DICOM file before the pixel data (to search values without matching pixel bytes by chance)."""
    blob = open(path, 'rb').read()
    end = blob.rfind(b'\xe0\x7f\x10\x00')
    return blob[:end] if end > 0 else blob


@pytest.fixture(scope='module')
def workspace():
    """Temporary folder of the module, deleted at the end (not kept by pytest like tmp_path folders)."""
    with tempfile.TemporaryDirectory(prefix='dicom_pseudo_real_') as folder:
        yield lambda name: pathlib.Path(tempfile.mkdtemp(prefix=name + '_', dir=folder))


@pytest.fixture(scope='module')
def sample(workspace):
    """
    Sample of the real dataset, linked into a temporary folder as series_XX/file_XXXX.dcm: returns (root, mosaic series
    folders). Series are chosen per (manufacturer, Siemens mosaic, 2D-like series with fewer than 10 files).
    """

    candidates = collections.defaultdict(list)
    for folder, _, names in sorted(os.walk(DATA)):
        files = sorted(os.path.join(folder, n) for n in names if not n.startswith('.'))
        files = [f for f in files if is_dicom(f)]
        if not files or len(files) > MAX_FILES:
            continue
        ds = pydicom.dcmread(files[0], stop_before_pixels=True)
        mosaic = 'MOSAIC' in [str(v).upper() for v in ds.get('ImageType', [])]
        candidates[(str(ds.get('Manufacturer', '')).split()[0].upper() if ds.get('Manufacturer') else '', mosaic, len(files) < 10)].append(files)
    root = workspace('real_raw')
    mosaics = set()
    for index, files in enumerate(f for group in sorted(candidates) for f in candidates[group][:SERIES_PER_TYPE]):
        folder = root / f'series_{index:02d}'
        folder.mkdir()
        for number, path in enumerate(files):
            os.symlink(path, folder / f'file_{number:04d}.dcm')
        if 'MOSAIC' in [str(v).upper() for v in pydicom.dcmread(files[0], stop_before_pixels=True).get('ImageType', [])]:
            mosaics.add(folder.name)
    assert len(list(root.iterdir())) >= 3, 'too few series sampled'
    return str(root), mosaics


@pytest.fixture(scope='module')
def real_key(workspace):
    path = str(workspace('real_secrets') / 'test.key')
    return path, load_key(path)


@pytest.fixture(scope='module')
def real_pseudonymized(sample, real_key, workspace):
    """Pseudonymize the sample (cached): real_pseudonymized(profile, processes) -> (output folder, linking table)."""
    cache = {}

    def run(profile: int = 1, processes: int = 1):
        if (profile, processes) not in cache:
            output = str(workspace(f'real_p{profile}_n{processes}'))
            link_table = os.path.join(os.path.dirname(real_key[0]), f'link_p{profile}_n{processes}.xlsx')
            pseudonymization(sample[0], output, profile, 'PatientID', progress_bar=False, key_file=real_key[0],
                             link_table=link_table, processes=processes)
            cache[(profile, processes)] = (output, link_table)
        return cache[(profile, processes)]

    return run


@pytest.fixture(scope='module')
def real_extracted(workspace):
    """Extract a folder (cached): real_extracted(input folder, profile) -> (output folder, overview table)."""
    cache = {}

    def run(input_root: str, profile: int = 1):
        if (input_root, profile) not in cache:
            output = str(workspace(f'real_extracted_p{profile}'))
            extraction(input_root, output, profile, progress_bar=False)
            cache[(input_root, profile)] = (output, read_table(os.path.join(output, 'metadata.xlsx'), dtype=str).set_index('Folder'))
        return cache[(input_root, profile)]

    return run


def check_outputs(raw_root: str, output: str, key: bytes, profile: int) -> dict:
    """Compare each raw file with its pseudonymized file (one file in memory at a time): counts and field names."""
    kept, kept_groups = select_profile(profile)
    kept_tags = {pydicom.tag.Tag(t) for t in kept.values()}
    outputs = {os.path.splitext(os.path.basename(p))[0]: p for p in glob.glob(os.path.join(output, '**', '*.dcm'), recursive=True)}
    result = collections.Counter()
    leaks, identifying = collections.Counter(), collections.Counter()
    for path in sorted(glob.glob(os.path.join(raw_root, '*', '*.dcm'))):
        raw = pydicom.dcmread(path)
        out_path = outputs.get(remap_uid(str(raw.SOPInstanceUID), key))
        result['files'] += 1
        if out_path is None:
            result['missing'] += 1
            continue
        out = pydicom.dcmread(out_path)
        result['pixel data different'] += raw.get('PixelData') != out.get('PixelData')
        result['identity flag missing'] += out.get('PatientIdentityRemoved') != 'YES'
        result['with private tags'] += any(e.tag.is_private for e in out.iterall())
        leaks.update(surviving_values(raw, out, kept_tags, kept_groups))
        blob = header_bytes(out_path)
        result['with an original UID'] += any(uid.encode() in blob for uid in original_uids(raw))
        # identifying values searched in the whole header, binary private elements (e.g. Siemens CSA) included
        identifying.update(field for value, field in sensitive_tokens(raw).items() if field in IDENTIFYING and len(value) >= 4 and value.encode() in blob)
    result['leaks'] = leaks
    result['identifying'] = identifying
    return result


def test_profile_1_removes_everything(sample, real_key, real_pseudonymized):
    output, _ = real_pseudonymized(1)
    result = check_outputs(sample[0], output, real_key[1], 1)
    assert result['files'] > 0 and result['missing'] == 0 and result['pixel data different'] == 0 and result['identity flag missing'] == 0
    assert result['with private tags'] == 0 and result['with an original UID'] == 0
    assert result['leaks'] == {} and result['identifying'] == {}


def test_profile_5_keeps_no_identity(sample, real_key, real_pseudonymized):
    """Profile 5 keeps vendor private elements (their content can hold original UIDs and the protocol name), but no identity."""
    output, _ = real_pseudonymized(5)
    result = check_outputs(sample[0], output, real_key[1], 5)
    assert result['files'] > 0 and result['missing'] == 0 and result['pixel data different'] == 0
    assert result['identifying'] == {}
    assert not {field.split(' -> ')[0] for field in result['leaks']} & IDENTIFYING


def test_parallel_equals_sequential(real_pseudonymized):
    sequential, table_1 = real_pseudonymized(1, 1)
    parallel, table_4 = real_pseudonymized(1, 4)
    files_1 = sorted(os.path.relpath(p, sequential) for p in glob.glob(os.path.join(sequential, '**', '*.dcm'), recursive=True))
    files_4 = sorted(os.path.relpath(p, parallel) for p in glob.glob(os.path.join(parallel, '**', '*.dcm'), recursive=True))
    assert len(files_1) == len(files_4) and files_1 == files_4
    different = sum(not filecmp.cmp(os.path.join(sequential, f), os.path.join(parallel, f), shallow=False) for f in files_1)
    assert different == 0
    assert read_table(table_1, dtype=str).equals(read_table(table_4, dtype=str))


def raw_to_output_folders(raw_root: str, link_table: str) -> dict:
    """Extraction folder of each raw series -> pseudonymized series folder."""
    raw_folder = {}
    for folder, files in group_by_folder_and_series(find_dicom_files(raw_root), raw_root).items():
        raw_folder[(os.path.dirname(os.path.relpath(files[0][0], raw_root)), str(files[0][1].SeriesInstanceUID))] = folder
    table = read_table(link_table, dtype=str)
    return {raw_folder[(row['Input folder'], row['Original SeriesInstanceUID'])]: row['Output folder'] for _, row in table.iterrows()}


def test_profile_5_extraction_equals_raw_extraction(sample, real_pseudonymized, real_extracted):
    """With the vendor private elements kept, the pseudonymized data gives the same NIfTI images as the raw data."""
    pseudo, link_table = real_pseudonymized(5)
    raw_output, raw_overview = real_extracted(sample[0], 5)
    pseudo_output, pseudo_overview = real_extracted(pseudo, 5)
    folders = raw_to_output_folders(sample[0], link_table)
    assert {folders[f] for f in raw_overview.index} == set(pseudo_overview.index)
    different = [raw for raw in raw_overview.index if not same_nifti(os.path.join(raw_output, raw), os.path.join(pseudo_output, folders[raw]))]
    assert different == []
    types = collections.Counter(raw_overview['NIfTI'])
    assert types['3D'] + types['4D'] > 0


def test_profile_1_mosaics_not_written_as_2d(sample, real_pseudonymized, real_extracted):
    """Without the Siemens private header, mosaics cannot be converted: reported, never written as 2D tiles."""
    if not sample[1]:
        pytest.skip('no Siemens mosaic in the sample')
    pseudo, link_table = real_pseudonymized(1)
    _, overview = real_extracted(pseudo, 1)
    output_folders = read_table(link_table, dtype=str).set_index('Input folder')['Output folder']
    mosaic_outputs = {output_folders[folder] for folder in sample[1]}
    assert len(mosaic_outputs & set(overview.index)) == 0

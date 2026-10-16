"""Pseudonymization of the test tree (pydicom data): coverage, privacy, integrity, linking table, safety checks."""

import collections
import filecmp
import glob
import os
import shutil
import subprocess
import sys

import numpy as np
import pydicom
import pytest
from pydicom.tag import Tag

from dicom_pseudo.core.pseudonym import load_key, pseudonym, remap_uid
from dicom_pseudo.core.settings import select_profile
from dicom_pseudo.core.tables import read_table
from dicom_pseudo.pseudonymization import pseudonymization

from helpers import original_uids, output_map, read_inputs, surviving_values


def _outputs(output):
    return {os.path.relpath(path, output): path for path in glob.glob(os.path.join(output, '**', '*'), recursive=True) if os.path.isfile(path)}


# ---------------------------------------------------------------- coverage and integrity

def test_every_input_is_pseudonymized(inputs, pseudonymized, key):
    output, _ = pseudonymized()
    mapping = output_map(inputs, output, key)
    assert len(mapping) == len(inputs)
    assert len(glob.glob(os.path.join(output, '**', '*.dcm'), recursive=True)) == len(inputs)
    assert not [path for path in _outputs(output) if not path.endswith('.dcm')], 'only DICOM files in the output'


def test_pixel_data_and_flags(inputs, pseudonymized, key):
    output, link_table = pseudonymized()
    table = read_table(link_table, dtype=str)
    table_pseudonyms = dict(zip(table['Original SeriesInstanceUID'], table['Pseudonym PatientID']))
    for path, out_path in output_map(inputs, output, key).items():
        raw, out = inputs[path], pydicom.dcmread(out_path)
        assert raw.get('PixelData') == out.get('PixelData'), path
        assert out.PatientIdentityRemoved == 'YES' and out.DeidentificationMethod.startswith('dicom_pseudo')
        assert out.PatientID == str(out.PatientName) == pseudonym(str(raw.PatientID), key) == table_pseudonyms[str(raw.SeriesInstanceUID)]


def test_uid_structure(inputs, pseudonymized, key):
    output, _ = pseudonymized()
    mapping = output_map(inputs, output, key)
    for keyword in ('StudyInstanceUID', 'SeriesInstanceUID', 'FrameOfReferenceUID', 'SOPInstanceUID'):
        original = {str(inputs[path].get(keyword)) for path in mapping if keyword in inputs[path]}
        new = {str(pydicom.dcmread(out, stop_before_pixels=True).get(keyword)) for path, out in mapping.items() if keyword in inputs[path]}
        assert len(original) == len(new), keyword


def test_references_are_remapped(inputs, pseudonymized, key):
    output, _ = pseudonymized()
    references = 0
    for path, out_path in output_map(inputs, output, key).items():
        original = sorted(str(e.value) for e in inputs[path].iterall() if e.keyword == 'ReferencedSOPInstanceUID')
        new = sorted(str(e.value) for e in pydicom.dcmread(out_path).iterall() if e.keyword == 'ReferencedSOPInstanceUID')
        assert new == sorted(remap_uid(uid, key) for uid in original)
        references += len(original)
    assert references > 0


@pytest.mark.parametrize('profile', [0, 1, 2, 3, 4])
def test_no_original_values_survive(inputs, pseudonymized, key, profile):
    output, _ = pseudonymized(profile)
    fields, groups = select_profile(profile)
    kept = {Tag(tag) for tag in fields.values()}
    found, uid_files = collections.Counter(), 0
    for path, out_path in output_map(inputs, output, key).items():
        found += surviving_values(inputs[path], pydicom.dcmread(out_path), kept, groups)
        blob = open(out_path, 'rb').read()
        uid_files += any(uid.encode() in blob for uid in original_uids(inputs[path]))
    assert not found, f'original values outside the kept fields: {dict(found)}'
    assert uid_files == 0


def test_kept_fields_are_unchanged(inputs, pseudonymized, key):
    output, _ = pseudonymized(1)
    fields, groups = select_profile(1)
    compare = {Tag(tag) for keyword, tag in fields.items() if keyword not in ('PatientName', 'PatientID', 'PatientIdentityRemoved', 'DeidentificationMethod')}
    changed = collections.Counter()
    for path, out_path in output_map(inputs, output, key).items():
        out = pydicom.dcmread(out_path)
        for elem in inputs[path]:
            if (elem.tag in compare or elem.tag.group in groups) and elem.VR != 'UI' and elem.tag.element != 0:
                if elem.tag not in out or out[elem.tag].value != elem.value:
                    changed[elem.keyword or str(elem.tag)] += 1
    assert not changed, dict(changed)


def test_private_tags_overlays_file_meta(inputs, pseudonymized, key):
    output, _ = pseudonymized(1)
    for out_path in output_map(inputs, output, key).values():
        out = pydicom.dcmread(out_path)
        assert not any(e.tag.is_private for e in out.iterall())
        assert not any(0x5000 <= e.tag.group < 0x6100 for e in out)
        assert {e.keyword for e in out.file_meta} <= {'FileMetaInformationGroupLength', 'FileMetaInformationVersion', 'MediaStorageSOPClassUID',
                                                      'MediaStorageSOPInstanceUID', 'TransferSyntaxUID', 'ImplementationClassUID', 'ImplementationVersionName'}
    assert any(0x6000 <= e.tag.group < 0x6100 for ds in inputs.values() for e in ds), 'test data contains an overlay'


def test_private_tag_kept_by_profile(inputs, pseudonymized, key):
    output, _ = pseudonymized(3)
    out = pydicom.dcmread(output_map(inputs, output, key)['single/CT_small.dcm'])
    assert [str(e.tag) for e in out if e.tag.is_private] == ['(0019,0010)', '(0019,1024)']


def test_sequences(inputs, pseudonymized, key):
    output, _ = pseudonymized(1)
    out = pydicom.dcmread(output_map(inputs, output, key)['agfa/ct0.dcm'])
    assert [(e.keyword, e.value) for e in out.PatientSizeCodeSequence[0]] == [('CodeValue', 'L'), ('CodeMeaning', 'Large')]
    assert len(inputs['agfa/ct0.dcm'].OtherPatientIDsSequence) == 2 and len(out.get('OtherPatientIDsSequence', [])) == 0


def test_cleared_fields_are_empty(inputs, pseudonymized, key):
    output, _ = pseudonymized(3)
    out = pydicom.dcmread(output_map(inputs, output, key)['agfa/ct0.dcm'])
    assert out.PatientWeight is None and out.StudyDate in (None, '')


def test_output_paths_are_pseudonymized(inputs, tree, pseudonymized, key):
    output, _ = pseudonymized()
    input_names = {part for path in inputs for part in path.split(os.sep)}
    identifiers = {str(ds.get(k, '')) for ds in inputs.values() for k in ('PatientID', 'PatientName', 'StudyDate')} - {''}
    for path, out_path in output_map(inputs, output, key).items():
        parts = os.path.relpath(out_path, output).split(os.sep)
        out = pydicom.dcmread(out_path, stop_before_pixels=True)
        assert parts == [out.PatientID[:len(parts[0])], out.StudyInstanceUID, out.SeriesInstanceUID, out.SOPInstanceUID + '.dcm']
        assert not set(parts) & (input_names | identifiers)


# ---------------------------------------------------------------- linking table

def test_linking_table(inputs, pseudonymized, key):
    output, link_table = pseudonymized()
    table = read_table(link_table, dtype=str)
    assert table['Number of files'].astype(int).sum() == len(inputs)
    assert set(table['Original PatientID']) == {str(ds.PatientID) for ds in inputs.values()}
    assert all(pseudonym(row['Original PatientID'], key) == row['Pseudonym PatientID'] for _, row in table.iterrows())
    key_columns = ['Input folder', 'Original SeriesInstanceUID', 'Output folder']
    assert table[key_columns].equals(table.sort_values(key_columns)[key_columns].reset_index(drop=True))
    assert not glob.glob(os.path.join(output, '**', '*.xlsx'), recursive=True)


def test_rerun_into_same_table(tree, key_file, tmp_path):
    table = str(tmp_path / 'link.csv')
    for _ in range(2):
        pseudonymization(os.path.join(tree, 'agfa'), str(tmp_path / 'out'), 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=table)
    rows = read_table(table, dtype=str)
    assert len(rows) == 1 and rows['Number of files'].tolist() == ['2']
    assert not os.path.exists(str(tmp_path / 'link_errors.csv'))


# ---------------------------------------------------------------- identifiers, linkage, keys

def test_agfa_identifier(tree, key_file, tmp_path):
    table = str(tmp_path / 'link.csv')
    pseudonymization(os.path.join(tree, 'agfa'), str(tmp_path / 'out'), 1, 'AgfaID', progress_bar=False, key_file=key_file, link_table=table)
    assert read_table(table, dtype=str)['Original AgfaID'].tolist() == ['AGFA-ACC-778899']


def test_missing_identifier_is_skipped(key_file, tmp_path):
    from pydicom.data import get_testdata_file
    from pydicom.uid import generate_uid
    for name, study_id in (('with.dcm', '42'), ('without.dcm', None)):
        ds = pydicom.dcmread(get_testdata_file('CT_small.dcm'))
        ds.SOPInstanceUID = generate_uid()
        if study_id is None:
            del ds.StudyID
        os.makedirs(tmp_path / 'in', exist_ok=True)
        ds.save_as(str(tmp_path / 'in' / name), enforce_file_format=True)
    table, output = str(tmp_path / 'link.csv'), str(tmp_path / 'out')
    pseudonymization(str(tmp_path / 'in'), output, 1, 'StudyID', progress_bar=False, key_file=key_file, link_table=table)
    errors = read_table(str(tmp_path / 'link_errors.csv'), dtype=str)
    assert errors['Status'].tolist() == ['skipped'] and errors['Input'].iloc[0].endswith('without.dcm')
    assert len(glob.glob(os.path.join(output, '**', '*.dcm'), recursive=True)) == 1


def test_study_linkage(inputs, pseudonymized, key):
    output, link_table = pseudonymized(1, 'study')
    mapping = output_map(inputs, output, key, 'study')
    assert len(mapping) == len(inputs)
    pseudonyms = collections.defaultdict(set)
    uids = collections.defaultdict(set)
    for path, out_path in mapping.items():
        out = pydicom.dcmread(out_path, stop_before_pixels=True)
        pseudonyms[str(inputs[path].PatientID)].add(out.PatientID)
        for elem in out.iterall():
            if elem.VR == 'UI' and elem.keyword not in ('SOPClassUID', 'MediaStorageSOPClassUID', 'ReferencedSOPClassUID'):
                uids[str(elem.value)].add((str(inputs[path].PatientID), str(inputs[path].StudyInstanceUID)))
    studies = collections.Counter(pid for pid, study in {(str(ds.PatientID), str(ds.StudyInstanceUID)) for ds in inputs.values()})
    assert all(len(pseudonyms[pid]) == n for pid, n in studies.items())
    assert not [uid for uid, owners in uids.items() if len({study for _, study in owners}) > 1 and len({pid for pid, _ in owners}) == 1]
    table = read_table(link_table, dtype=str)
    assert all(pseudonym(row['Original PatientID'], key) == row['Patient pseudonym PatientID'] for _, row in table.iterrows())


def test_other_key_gives_other_pseudonyms(tree, inputs, pseudonymized, key, tmp_path):
    output, _ = pseudonymized()
    again = str(tmp_path / 'again')
    key_file = str(tmp_path / 'other.key')
    pseudonymization(tree, again, 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=str(tmp_path / 'other.xlsx'))
    other = output_map(inputs, again, load_key(key_file))
    first = output_map(inputs, output, key)
    assert len(other) == len(first)
    assert not {os.path.basename(p) for p in first.values()} & {os.path.basename(p) for p in other.values()}


def test_rerun_is_identical(tree, key_file, pseudonymized, tmp_path):
    output, _ = pseudonymized()
    again = str(tmp_path / 'again')
    pseudonymization(tree, again, 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=str(tmp_path / 'again.xlsx'))
    first, second = _outputs(output), _outputs(again)
    assert first.keys() == second.keys() and all(filecmp.cmp(first[p], second[p], shallow=False) for p in first)


def test_batches_give_the_same_pseudonyms(tree, inputs, key_file, key, pseudonymized, tmp_path):
    output, _ = pseudonymized()
    batches = str(tmp_path / 'batches')
    for batch in ('cohort/98892001', 'cohort/98892003'):
        pseudonymization(os.path.join(tree, batch), batches, 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=str(tmp_path / 'link.xlsx'))
    batch_files = {os.path.relpath(p, batches) for p in glob.glob(os.path.join(batches, '**', '*.dcm'), recursive=True)}
    assert batch_files and batch_files <= {os.path.relpath(p, output) for p in glob.glob(os.path.join(output, '**', '*.dcm'), recursive=True)}
    assert len(read_table(str(tmp_path / 'link.xlsx'), dtype=str)) == len({(str(ds.SeriesInstanceUID), os.path.dirname(p)) for p, ds in inputs.items() if p.startswith(('cohort/98892001', 'cohort/98892003'))})


# ---------------------------------------------------------------- inputs and safety checks

def test_edge_cases(edge_tree, key_file, key, tmp_path):
    output, table = str(tmp_path / 'out'), str(tmp_path / 'link.csv')
    pseudonymization(edge_tree, output, 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=table)
    written = glob.glob(os.path.join(output, '**', '*'), recursive=True)
    assert len([p for p in written if os.path.isfile(p)]) == 2, 'ok.dcm (or its duplicate copy) and nopreamble.dcm'
    errors = read_table(str(tmp_path / 'link_errors.csv'), dtype=str)
    reasons = {os.path.basename(row['Input']): row['Error'] for _, row in errors.iterrows()}
    assert set(reasons) == {'broken.dcm', 'ok.dcm'} or set(reasons) == {'broken.dcm', 'duplicate.dcm'}
    assert any('duplicate SOPInstanceUID' in error for error in reasons.values())
    assert any('not a valid DICOM dataset' in error for error in reasons.values())


def test_single_file_input(tree, key_file, tmp_path):
    output = str(tmp_path / 'out')
    pseudonymization(os.path.join(tree, 'single', 'CT_small.dcm'), output, 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=str(tmp_path / 'l.csv'))
    assert len(glob.glob(os.path.join(output, '**', '*.dcm'), recursive=True)) == 1


@pytest.mark.parametrize('case', ['output inside input', 'table inside output', 'key inside output', 'no table', 'unknown identifier', 'unknown linkage'])
def test_refused_configurations(tree, key_file, tmp_path, case):
    output, table, key = str(tmp_path / 'out'), str(tmp_path / 'link.csv'), key_file
    identifier, linkage = 'PatientID', 'patient'
    if case == 'output inside input':
        output = os.path.join(tree, 'out')
    elif case == 'table inside output':
        table = os.path.join(output, 'link.csv')
    elif case == 'key inside output':
        key = os.path.join(output, 'key')
    elif case == 'no table':
        table = None
    elif case == 'unknown identifier':
        identifier = 'Unknown'
    else:
        linkage = 'unknown'
    with pytest.raises(SystemExit):
        pseudonymization(tree, output, 1, identifier, progress_bar=False, key_file=key, link_table=table, linkage=linkage)
    assert not os.path.exists(os.path.join(tree, 'out'))


def test_run_lock(tree, key_file, tmp_path):
    table = str(tmp_path / 'link.csv')
    open(table + '.lock', 'w').write(f'{os.uname().nodename} {os.getpid()}')
    with pytest.raises(SystemExit, match='used by another run'):
        pseudonymization(os.path.join(tree, 'agfa'), str(tmp_path / 'out'), 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=table)
    open(table + '.lock', 'w').write(f'{os.uname().nodename} 999999')
    pseudonymization(os.path.join(tree, 'agfa'), str(tmp_path / 'out'), 1, 'PatientID', progress_bar=False, key_file=key_file, link_table=table)
    assert not os.path.exists(table + '.lock') and os.path.exists(table)


def test_command_line(tree, key_file, tmp_path):
    command = os.path.join(os.path.dirname(sys.executable), 'pseudonymize')
    result = subprocess.run([command, os.path.join(tree, 'with space'), '-o', str(tmp_path / 'out put'), '-k', key_file, '-l', str(tmp_path / 'l.xlsx'), '-n', '2'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-500:] + result.stderr[-500:]
    assert '2 file(s) in 1 series pseudonymized.' in result.stdout
    assert len(glob.glob(str(tmp_path / 'out put' / '**' / '*.dcm'), recursive=True)) == 2

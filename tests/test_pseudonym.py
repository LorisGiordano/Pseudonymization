"""Secret key, pseudonyms and pseudonymized UIDs."""

import hashlib
import os
import stat

import pytest
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

from dicom_pseudo.core.pseudonym import compute_pseudonyms, load_key, pseudo_uid, pseudonym, remap_uid


def test_new_key_file(tmp_path):
    path = str(tmp_path / 'keys' / 'project.key')
    key = load_key(path)
    assert len(key) == 64 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_key(path) == key


def test_key_from_environment(monkeypatch):
    monkeypatch.setenv('DICOM_PSEUDO_KEY', 'x' * 32)
    assert load_key() == b'x' * 32
    monkeypatch.setenv('DICOM_PSEUDO_KEY', 'short')
    with pytest.raises(SystemExit):
        load_key()
    monkeypatch.delenv('DICOM_PSEUDO_KEY')
    with pytest.raises(SystemExit):
        load_key()


def test_pseudonyms_are_keyed():
    key_a, key_b = b'a' * 32, b'b' * 32
    assert pseudonym('12345678', key_a) == pseudonym('12345678', key_a)
    assert pseudonym('12345678', key_a) != pseudonym('12345678', key_b)
    assert pseudonym('12345678', key_a) != hashlib.sha256(b'12345678').hexdigest()


def test_linkage_levels():
    key = b'k' * 32
    patient_1, patient_pseudo = compute_pseudonyms('ID1', '1.2.3', key, 'patient')
    assert patient_1 == patient_pseudo
    study_1, patient_pseudo_1 = compute_pseudonyms('ID1', '1.2.3', key, 'study')
    study_2, patient_pseudo_2 = compute_pseudonyms('ID1', '1.2.4', key, 'study')
    assert study_1 != study_2 and patient_pseudo_1 == patient_pseudo_2 == patient_1
    with pytest.raises(SystemExit):
        compute_pseudonyms('ID1', '1.2.3', key, 'unknown')


def test_pseudonymized_uids():
    key = b'k' * 32
    uid = pseudo_uid('1.2.826.0.1.3680043.8.498.1', key)
    assert uid.startswith('2.25.') and len(uid) <= 64 and uid == pseudo_uid('1.2.826.0.1.3680043.8.498.1', key)
    assert pseudo_uid('1.2.3', key, scope='study A') != pseudo_uid('1.2.3', key, scope='study B')
    assert remap_uid(CTImageStorage, key) == CTImageStorage and remap_uid(ExplicitVRLittleEndian, key) == ExplicitVRLittleEndian
    assert remap_uid('', key) == ''

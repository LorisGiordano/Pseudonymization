"""Configuration and profiles."""

import json

import pytest
from pydicom.datadict import tag_for_keyword

from dicom_pseudo.core import settings
from dicom_pseudo.core.settings import FIELDS_TO_KEEP, PROFILES, select_profile


@pytest.mark.parametrize('profile', [0, 1, 2, 3, 4, 5])
def test_profiles_load(profile):
    fields, groups = select_profile(profile)
    assert set(FIELDS_TO_KEEP) <= set(fields)
    assert {0x0002, 0x0028, 0x7fe0} <= groups


def test_unknown_profile():
    with pytest.raises(SystemExit):
        select_profile(99)


def test_profiles_do_not_leak_into_each_other():
    number_of_fields = len(FIELDS_TO_KEEP)
    fields_1, _ = select_profile(1)
    fields_3, _ = select_profile(3)
    assert 'PatientAge' in fields_1 and 'PatientAge' not in fields_3
    assert len(FIELDS_TO_KEEP) == number_of_fields


def test_profile_contents():
    assert {'StudyDate', 'SeriesDate', 'PatientAge'} <= set(select_profile(2)[0])
    assert {'NumberOfTemporalPositions', 'TemporalPositionIdentifier', 'ContentTime'} <= set(select_profile(3)[0])
    machine = set(select_profile(4)[0])
    assert {'ManufacturerModelName', 'SoftwareVersions', 'KVP'} <= machine
    assert not {'DeviceSerialNumber', 'StationName', 'InstitutionName', 'ProtocolName', 'PatientAge'} & machine
    conversion = select_profile(5)[0]
    assert {conversion['SiemensCSASeriesHeader'], conversion['PhilipsBValue'], conversion['GEBValue']} == {0x00291020, 0x20011003, 0x00431039}


def test_standard_keywords_match_their_tags():
    """Every standard keyword used in the configuration has the tag of the DICOM dictionary."""
    for profile in PROFILES:
        for keyword, tag in select_profile(int(profile))[0].items():
            standard = tag_for_keyword(keyword)
            if standard is not None:
                assert standard == tag, keyword


def test_tag_formats(tmp_path):
    """Tags given as hex string, keyword or int, grouped by category."""
    path = tmp_path / 'tags.json'
    path.write_text(json.dumps({'A': {'PatientAge': '0x00101010', 'PatientSex': 'PatientSex'}, 'PatientWeight': 1052720}))
    assert settings.load_tags(str(path)) == {'PatientAge': 0x00101010, 'PatientSex': 0x00100040, 'PatientWeight': 0x00101030}


def test_invalid_configuration(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{"PatientAge": "0x00101010",}')
    with pytest.raises(SystemExit, match='Invalid configuration file'):
        settings.load_tags(str(path))
    path.write_text('{"PatientAge": "NotAKeyword"}')
    with pytest.raises(SystemExit, match='Invalid tag'):
        settings.load_tags(str(path))

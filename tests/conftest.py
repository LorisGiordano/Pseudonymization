"""
Shared fixtures: test input trees (pydicom data), test keys, and pseudonymization runs (cached per configuration).
"""

import os

import pytest

from dicom_pseudo.core.pseudonym import load_key
from dicom_pseudo.pseudonymization import pseudonymization

from helpers import build_edge_tree, build_tree, read_inputs


@pytest.fixture(scope='session')
def tree(tmp_path_factory):
    """Test input tree built from the pydicom data (see helpers.build_tree)."""
    return build_tree(str(tmp_path_factory.mktemp('input')))


@pytest.fixture(scope='session')
def inputs(tree):
    """Valid DICOM inputs of the test tree: relative path -> dataset."""
    return read_inputs(tree)


@pytest.fixture(scope='session')
def edge_tree(tmp_path_factory):
    """Edge cases (see helpers.build_edge_tree)."""
    return build_edge_tree(str(tmp_path_factory.mktemp('edge')))


@pytest.fixture(scope='session')
def secrets(tmp_path_factory):
    """Folder for keys and linking tables (outside all outputs)."""
    return str(tmp_path_factory.mktemp('secrets'))


@pytest.fixture(scope='session')
def key_file(secrets):
    """Test key file (created by load_key)."""
    path = os.path.join(secrets, 'test.key')
    load_key(path)
    return path


@pytest.fixture(scope='session')
def key(key_file):
    return load_key(key_file)


@pytest.fixture(scope='session')
def pseudonymized(tree, key_file, secrets, tmp_path_factory):
    """
    Pseudonymize the test tree (cached per configuration): pseudonymized(profile=1, linkage='patient', processes=1)
    returns (output folder, linking table path).
    """

    cache = {}

    def run(profile: int = 1, linkage: str = 'patient', processes: int = 1, identifier: str = 'PatientID'):
        configuration = (profile, linkage, processes, identifier)
        if configuration not in cache:
            name = f'p{profile}_{linkage}_n{processes}_{identifier}'
            output = str(tmp_path_factory.mktemp(name))
            link_table = os.path.join(secrets, f'{name}.xlsx')
            pseudonymization(tree, output, profile, identifier, progress_bar=False, key_file=key_file, link_table=link_table,
                             linkage=linkage, processes=processes)
            cache[configuration] = (output, link_table)
        return cache[configuration]

    return run

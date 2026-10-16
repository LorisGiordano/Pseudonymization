"""Parallel pseudonymization: same results as one process, folder locks, crashed processes."""

import filecmp
import glob
import json
import os
import time
from concurrent.futures.process import BrokenProcessPool

import pytest

from dicom_pseudo.core.tables import read_table
from dicom_pseudo.pseudonymization.parallel import run_parallel


def test_parallel_equals_sequential(pseudonymized):
    sequential, table_1 = pseudonymized(processes=1)
    parallel, table_4 = pseudonymized(processes=4)
    files_1 = {os.path.relpath(p, sequential) for p in glob.glob(os.path.join(sequential, '**', '*'), recursive=True) if os.path.isfile(p)}
    files_4 = {os.path.relpath(p, parallel) for p in glob.glob(os.path.join(parallel, '**', '*'), recursive=True) if os.path.isfile(p)}
    assert files_1 == files_4
    assert all(filecmp.cmp(os.path.join(sequential, f), os.path.join(parallel, f), shallow=False) for f in files_1)
    assert read_table(table_1, dtype=str).equals(read_table(table_4, dtype=str))


def record_task(folder, paths, record_dir):
    """Task of the scheduler test: records its start and end time."""
    start = time.time()
    time.sleep(0.6)
    with open(os.path.join(record_dir, folder + '.json'), 'w') as file:
        json.dump([start, time.time()], file)
    return folder


def crash_task(folder, paths):
    """Task of the crash test: the process stops abruptly."""
    os._exit(1)


def test_folders_sharing_a_lock_never_run_together(tmp_path):
    locks = {'a1': {'series X'}, 'b': {'series Y'}, 'a2': {'series X'}, 'c': {'series Z'}}
    folders = [(name, []) for name in locks]
    results = list(run_parallel(folders, 4, record_task, {'record_dir': str(tmp_path)}, lambda folder, paths: frozenset(locks[folder])))
    assert sorted(results) == sorted(locks)
    times = {name: json.load(open(tmp_path / f'{name}.json')) for name in locks}
    overlap = lambda x, y: times[x][0] < times[y][1] and times[y][0] < times[x][1]
    assert not overlap('a1', 'a2') and times['a1'][1] <= times['a2'][0], 'same lock: one after the other, in input order'
    assert overlap('a1', 'b') and overlap('a1', 'c'), 'different locks: in parallel'


def test_crashed_process_is_reported(tmp_path):
    with pytest.raises(BrokenProcessPool):
        list(run_parallel([('x', [])], 2, crash_task, {}, lambda folder, paths: frozenset({folder})))

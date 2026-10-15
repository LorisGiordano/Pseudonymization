"""
Parallel processing of the folders of an input: one task per folder, run in a pool of processes.

Safety:
    - locks: a folder is only launched if none of its locks (PatientID, StudyInstanceUID, SeriesInstanceUID of its
      files) is held by a running folder, or by a folder waiting before it (folders sharing a series are processed one
      after the other, in input order, as in a sequential run)
    - bounded memory (huge datasets): folders are read lazily from the input, only the running folders and a small
      queue of folders waiting to be launched are held in memory
    - the tasks only write their own output files: everything shared (key, linking table, report) stays in the parent
"""

""" IMPORTS """

# Pre-installed packages
import sys
import signal
from collections import deque
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

# Pydicom
import pydicom
from pydicom.tag import Tag

# Core modules
from ..core.settings import IDENTIFIERS
from ..core.identity import get_identifier_value


""" LOCKS """

def folder_locks(folder: str, paths: list[str], identifier: str) -> frozenset:
    """
    Get the locks of a folder: (identifier value, StudyInstanceUID, SeriesInstanceUID) of each of its files, read from
    the file headers only. A file whose header cannot be read locks the folder itself (its error is reported by the
    task processing the folder).

    Inputs:
        - folder: str = relative input folder
        - paths: list[str] = paths to the DICOM files of the folder
        - identifier: str = DICOM keyword used as identifier

    Outputs:
        - locks: frozenset = locks of the folder
    """

    tags = [Tag(tag) for tag in IDENTIFIERS[identifier]] + [Tag('StudyInstanceUID'), Tag('SeriesInstanceUID')]
    locks = set()
    for path in paths:
        try:
            dicom_data = pydicom.dcmread(path, stop_before_pixels=True, force=True, specific_tags=tags)
            original_id, _ = get_identifier_value(dicom_data, identifier)
            locks.add((original_id, str(dicom_data.get('StudyInstanceUID', '')), str(dicom_data.get('SeriesInstanceUID', ''))))
        except Exception:
            locks.add(('folder', folder))
    return frozenset(locks)


""" PROCESS POOL """

# Settings of the tasks, set once per process (see _initialize)
_SETTINGS = {}

def _initialize(settings: dict) -> None:
    """
    Initialize a process of the pool with the settings shared by all its tasks (e.g. key, profile). A process stopped
    by the pool (SIGTERM, e.g. when another process crashed) exits normally, so that a file being written is cleaned up.
    """

    _SETTINGS.update(settings)
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

def _run(function, folder: str, paths: list[str]):
    """
    Run a task in a process of the pool: function(folder, paths, **settings).
    """

    return function(folder, paths, **_SETTINGS)

def run_parallel(folders, processes: int, function, settings: dict, locks, lookahead: int = 4):
    """
    Process folders in parallel, one task per folder, launched in input order as soon as a process is free and the
    locks of the folder are available.

    Inputs:
        - folders: iterable = (folder, paths) of the input, read lazily
        - processes: int = number of processes
        - function: callable = task function(folder, paths, **settings), top-level function (picklable)
        - settings: dict = settings of the tasks, sent once to each process
        - locks: callable = locks(folder, paths) -> frozenset of the locks of a folder
        - lookahead: int = number of folders waiting to be launched, per process (default = 4)

    Outputs (generator):
        - result = result of each task, in order of completion
    """

    folders = iter(folders)
    exhausted = False
    pending = deque()       # (folder, paths, locks) waiting to be launched, in input order
    running = {}            # future -> locks of the running folders

    with ProcessPoolExecutor(max_workers=processes, initializer=_initialize, initargs=(settings,)) as pool:
        try:
            while True:

                # read the next folders of the input (bounded queue)
                while not exhausted and len(pending) < lookahead * processes:
                    try:
                        folder, paths = next(folders)
                    except StopIteration:
                        exhausted = True
                        break
                    pending.append((folder, paths, locks(folder, paths)))

                # launch the folders whose locks are free, in input order (a folder also waits for the folders sharing
                # a lock that are waiting before it)
                blocked = set().union(*running.values())
                waiting = deque()
                while pending:
                    folder, paths, folder_locks_ = pending.popleft()
                    if len(running) < processes and not (folder_locks_ & blocked):
                        running[pool.submit(_run, function, folder, paths)] = folder_locks_
                    else:
                        waiting.append((folder, paths, folder_locks_))
                    blocked |= folder_locks_
                pending = waiting

                # all folders processed
                if not running:
                    break

                # results of the finished folders, their locks are released
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    running.pop(future)
                    yield future.result()

        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise

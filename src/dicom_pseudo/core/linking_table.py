"""
Linking table between original and pseudonymized identifiers, one row per DICOM series (and input/output folder).
The linking table allows to re-identify the data and must be stored separately from the pseudonymized data.
"""

""" IMPORTS """

# Pre-installed packages
import os
import socket

# Pandas
import pandas as pd

# Pydicom
import pydicom

# Core modules
from .identity import SeriesIdentity
from .tables import read_table, write_table


""" DEFINITIONS """

# Series information stored in the linking table (read from the original DICOM)
SERIES_INFORMATION = ('Modality', 'SeriesNumber', 'SeriesDescription', 'BurnedInAnnotation')

# Columns identifying a row of the linking table (series per input and output folder), also used to sort the rows
ROW_KEY = ('Input folder', 'Original SeriesInstanceUID', 'Output folder')


""" FUNCTIONS """

def link_record(identity: SeriesIdentity, dicom_data: pydicom.dataset.Dataset, input_folder: str) -> dict:
    """
    Create the linking table record of a series.

    Inputs:
        - identity: SeriesIdentity = identity of the series
        - dicom_data: pydicom.dataset.Dataset = original dicom file object of the series
        - input_folder: str = relative input folder(s) of the series

    Outputs:
        - record: dict = linking table record (number of files still 0)
    """

    identifier = identity.identifier
    return {
        f'Original {identifier}': identity.original_id,
        f'Pseudonym {identifier}': identity.pseudo_id,
        f'Patient pseudonym {identifier}': identity.patient_pseudo_id,
        'Linkage': identity.linkage,
        'Original StudyInstanceUID': identity.original_study_uid,
        'Original SeriesInstanceUID': identity.original_series_uid,
        'Pseudonymized StudyInstanceUID': identity.pseudo_study_uid,
        'Pseudonymized SeriesInstanceUID': identity.pseudo_series_uid,
        **{keyword: str(dicom_data.get(keyword, '')) for keyword in SERIES_INFORMATION},
        'Output folder': identity.output_folder,
        'Input folder': input_folder,
        'Number of files': 0,
    }

def add_record(series_records: dict, record: dict, identifier: str, number_of_files: int = 1) -> None:
    """
    Add a record to the linking table records: one record per series and input/output folder, counting its files.

    Inputs:
        - series_records: dict = linking table records, updated in place
        - record: dict = linking table record (see link_record)
        - identifier: str = DICOM keyword used as identifier
        - number_of_files: int = number of files of the record to add (default = 1)
    """

    record_key = (record[f'Original {identifier}'], record['Original SeriesInstanceUID'], record['Input folder'], record['Output folder'])
    if record_key not in series_records:
        series_records[record_key] = record
    series_records[record_key]['Number of files'] += number_of_files

def merge_records(series_records: dict, new_records: dict) -> None:
    """
    Merge linking table records (e.g. of a folder processed in another process) into the records of the run, adding
    up the number of files of records of the same series and input/output folder.

    Inputs:
        - series_records: dict = linking table records of the run, updated in place
        - new_records: dict = linking table records to merge (see add_record)
    """

    for record_key, record in new_records.items():
        if record_key in series_records:
            series_records[record_key]['Number of files'] += record['Number of files']
        else:
            series_records[record_key] = record

def save_link_table(link_table: str, series_records: dict, identifier: str) -> None:
    """
    Save the linking table (one row per DICOM series), merged with the existing linking table if any.

    Inputs:
        - link_table: str = path to linking table (.xlsx or .csv)
        - series_records: dict = linking table records, one per series
        - identifier: str = DICOM keyword used as identifier
    """

    if not series_records:
        return

    df = pd.DataFrame(list(series_records.values())).astype(str)

    # merge with existing linking table, newer rows replace older rows of the same series
    if os.path.exists(link_table):
        existing = read_table(link_table, dtype=str)
        df = pd.concat([existing, df], ignore_index=True)
        subset = [column for column in (f'Original {identifier}', 'Original SeriesInstanceUID', 'Input folder', 'Output folder') if column in df.columns]
        df = df.drop_duplicates(subset=subset, keep='last')

    # rows sorted, so that the table does not depend on the processing order (e.g. parallel processing)
    df = df.sort_values([column for column in ROW_KEY if column in df.columns], kind='stable').reset_index(drop=True)
    write_table(df, link_table)


""" RUN LOCK """

def _process_running(pid: int) -> bool:
    """
    Check whether a process is running on this computer.
    """

    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259                                         # STILL_ACTIVE
    try:
        os.kill(pid, 0)                                                         # signal 0: existence check only
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def acquire_run_lock(link_table: str) -> str:
    """
    Lock the linking table for this run (<link_table>.lock, containing the host name and process ID), so that two runs
    never update the same linking table at the same time. A lock left by a process that is no longer running on this
    computer (e.g. after a crash) is taken over.

    Inputs:
        - link_table: str = path to linking table

    Outputs:
        - lock_path: str = path to the lock file (see release_run_lock)
    """

    lock_path = link_table + '.lock'
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    content = f'{socket.gethostname()} {os.getpid()}'
    for _ in range(2):
        try:
            file_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                with open(lock_path, 'r') as file:
                    host, pid = file.read().split()
            except (OSError, ValueError):
                host, pid = '', '0'
            if host == socket.gethostname() and not _process_running(int(pid)):
                print(f"WARNING: Lock of a run that is no longer running removed: '{lock_path}'.")
                os.remove(lock_path)
                continue
            raise SystemExit(f"The linking table '{link_table}' is used by another run ({host or 'unknown host'}, process {pid}). "
                             f"Wait for it to finish, or remove '{lock_path}' if no other run is using the linking table.")
        with os.fdopen(file_descriptor, 'w') as file:
            file.write(content)
        return lock_path
    raise SystemExit(f"The linking table '{link_table}' could not be locked ('{lock_path}').")

def release_run_lock(lock_path: str) -> None:
    """
    Release the lock of the linking table (see acquire_run_lock).
    """

    if lock_path and os.path.exists(lock_path):
        os.remove(lock_path)

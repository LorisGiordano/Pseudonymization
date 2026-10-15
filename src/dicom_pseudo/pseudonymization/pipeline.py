"""
Pseudonymization of DICOM files: one pseudonymized DICOM file per input file.

The input is processed folder by folder, read lazily (huge datasets), in one process or in parallel in several
processes (one task per folder, see parallel.py). Both give the same output files and linking table.
"""

""" IMPORTS """

# Pre-installed packages
import os
import csv
import multiprocessing
from concurrent.futures.process import BrokenProcessPool

# Tqdm [optional]
try:
    from tqdm import tqdm
    PROGRESS_BAR = True
except:
    print("INFO: Progress bar not available because tqdm is not installed.")
    PROGRESS_BAR = False

# Pydicom
import pydicom
from pydicom.tag import Tag

# Core modules
from ..core.settings import IDENTIFIERS, LINKAGES, TOOL_NAME, TOOL_VERSION, select_profile
from ..core.pseudonym import load_key
from ..core.identity import identify
from ..core.files import iter_dicom_folders, save_dicom
from ..core.paths import check_paths
from ..core.linking_table import link_record, add_record, merge_records, save_link_table, acquire_run_lock, release_run_lock
from ..core.report import report

# Pseudonymization modules
from .deidentification import write_pseudonym, remap_uids
from .sanitization import remove_private_tags, sanitize_dataset, ensure_file_meta
from .parallel import folder_locks, run_parallel


""" FUNCTIONS """

def pseudonymize_dicom(input_path: str, input_folder: str, output_root: str, identifier: str, key: bytes, deidentification_method: str, fields_to_keep: dict, groups_to_keep: set, linkage: str = 'patient', run_start: int = None) -> dict:
    """
    Pseudonymize a single DICOM file, saved as <output>/<pseudonym[:16]>/<StudyInstanceUID>/<SeriesInstanceUID>/<SOPInstanceUID>.dcm
    (pseudonymized values only).

    Inputs:
        - input_path: str = path to DICOM file
        - input_folder: str = relative input folder of the file (stored in the linking table)
        - output_root: str = path to output folder
        - identifier: str = DICOM keyword to be used as identifier
        - key: bytes = secret key used to compute the pseudonyms
        - deidentification_method: str = description stored in DeidentificationMethod
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
        - linkage: str = 'patient' or 'study' level pseudonyms and UIDs (default = 'patient')
        - run_start: int = start of the run (file system time, ns): an output file written since then is a duplicate
                           instance of this run (default = None => no duplicate check)

    Outputs:
        - record: dict = linking table record of the series of this file (None if identifier missing, file not written)
    """

    # load the DICOM file
    dicom_data = pydicom.dcmread(input_path, force=True)
    if 'SOPClassUID' not in dicom_data or 'SOPInstanceUID' not in dicom_data:
        raise ValueError("not a valid DICOM dataset (damaged file or no SOP Class/Instance UID)")

    # identity of the series and its linking table record (from the original data), files without identifier are not written
    identity = identify(dicom_data, identifier, key, linkage)
    if identity is None:
        return None
    record = link_record(identity, dicom_data, input_folder)

    # write the pseudonym, replace all instance UIDs (study, series, instance, frame of reference, references) consistently
    write_pseudonym(dicom_data, identity, deidentification_method)
    remap_uids(dicom_data, key, identity.uid_scope)

    # remove private elements and anonymize other DICOM fields (excluding essential metadata)
    tags_to_keep = {Tag(tag) for tag in fields_to_keep.values()}
    remove_private_tags(dicom_data, tags_to_keep)
    sanitize_dataset(dicom_data, tags_to_keep, groups_to_keep)

    # ensure file meta data reflects the new dataset state
    ensure_file_meta(dicom_data)

    # output path built from pseudonymized values, an instance is only written once per run (an existing file written
    # since the start of the run is a duplicate; older files, of a previous run, are replaced)
    output_path = os.path.join(output_root, identity.output_folder, f'{dicom_data.SOPInstanceUID}.dcm')
    if run_start is not None and os.path.exists(output_path) and os.stat(output_path).st_mtime_ns >= run_start:
        raise ValueError("duplicate SOPInstanceUID (instance already pseudonymized from another file in this run)")

    # save the pseudonymized DICOM file
    save_dicom(dicom_data, output_path)

    return record

def pseudonymize_folder(folder: str, paths: list[str], **settings) -> dict:
    """
    Pseudonymize the DICOM files of one input folder (task run in this process, or in a process of the pool).

    Inputs:
        - folder: str = relative input folder
        - paths: list[str] = paths to the DICOM files of the folder
        - settings = arguments of pseudonymize_dicom shared by all files (output_root, identifier, key, ...)

    Outputs:
        - result: dict = linking table records of the folder ('records'), number of files ('files'), skipped files
                         ('skipped') and failed files with their error ('failed')
    """

    records, skipped, failed = {}, [], []
    for path in paths:
        try:
            record = pseudonymize_dicom(path, folder, **settings)
        except Exception as error:
            failed.append((path, f'{type(error).__name__}: {error}'))
            continue
        if record is None:
            skipped.append(path)
            continue
        add_record(records, record, settings['identifier'])
    return {'records': records, 'files': len(paths), 'skipped': skipped, 'failed': failed}

class _Errors:
    """
    Skipped and failed inputs of a run: written to an error log (all of them, so that nothing accumulates in memory),
    counted, and the first examples kept for the report.
    """

    def __init__(self, path: str, examples: int = 10):
        self.path, self.examples = path, examples
        self.skipped, self.failed, self.skipped_total, self.failed_total = [], [], 0, 0
        if os.path.exists(path):
            os.remove(path)

    def add(self, skipped: list, failed: list) -> None:
        if not skipped and not failed:
            return
        new = not os.path.exists(self.path)
        with open(self.path, 'a', newline='', encoding='utf-8-sig' if new else 'utf-8') as file:
            writer = csv.writer(file)
            if new:
                writer.writerow(['Status', 'Input', 'Error'])
            writer.writerows([('skipped', path, 'identifier missing') for path in skipped] + [('failed', path, error) for path, error in failed])
        self.skipped += skipped[:max(0, self.examples - len(self.skipped))]
        self.failed += failed[:max(0, self.examples - len(self.failed))]
        self.skipped_total += len(skipped)
        self.failed_total += len(failed)

def pseudonymization(input_root: str, output_root: str, profile: int, identifier: str, progress_bar: bool = PROGRESS_BAR, key_file: str = None, link_table: str = None, linkage: str = 'patient', processes: int = 1) -> None:
    """
    Main function to pseudonymize a DICOM directory (or a single DICOM file).

    Inputs:
        - input_root: str = path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = path to output folder
        - profile: int = number corresponding to profile to be selected
        - identifier: str = DICOM keyword to be used as identifier
        - progress_bar: bool = (default = PROGRESS_BAR)
        - key_file: str = path to file containing the secret pseudonymization key, created if it does not exist
                          (default = None => key read from environment variable KEY_ENV_VARIABLE)
        - link_table: str = path to the linking table (.xlsx or .csv) between original and pseudo identifiers,
                            one row per DICOM series; must be located outside the output folder
        - linkage: str = 'patient' (studies of the same patient share the pseudonym) or 'study' (one pseudonym
                         per study, studies of the same patient cannot be linked without the key) (default = 'patient')
        - processes: int = number of processes: 0 or 1 = one process, more = one task per input folder in parallel
                           (default = 1)
    """

    # a pseudonymization started in a worker process: the script calling the pseudonymization was imported again by
    # the processes of the pool (spawn start method, e.g. macOS, Windows), as it is not protected by
    # if __name__ == '__main__':
    if getattr(multiprocessing.current_process(), '_inheriting', False):
        raise SystemExit("pseudonymization() called in a worker process: protect the code of your script that calls it with "
                         "if __name__ == '__main__': (required by Python multiprocessing).")

    # check inputs and locations before doing anything, load the key (in this process only)
    if identifier not in IDENTIFIERS:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(IDENTIFIERS)})")
    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")
    if processes < 0:
        raise SystemExit(f"Number of processes must be 0 or more (given: {processes}).")
    input_folder, single_file = check_paths(input_root, output_root, link_table, key_file)
    key = load_key(key_file)
    if processes > (os.cpu_count() or 1):
        print(f"WARNING: {processes} processes requested for {os.cpu_count()} CPUs.")

    # fields to keep and description of the de-identification
    fields_to_keep, groups_to_keep = select_profile(profile)
    deidentification_method = f"{TOOL_NAME} {TOOL_VERSION} profile {profile} {identifier} {linkage}-level"[:64]  # LO: max 64 chars

    # lock of the linking table (no other run at the same time), start of the run (file system time of the output)
    lock = acquire_run_lock(link_table)
    os.makedirs(output_root, exist_ok=True)
    marker = os.path.join(output_root, f'.pseudonymization-run-{os.getpid()}')
    series_records, number_of_files, interrupted = {}, 0, None
    errors = _Errors(os.path.splitext(link_table)[0] + '_errors.csv')
    try:
        with open(marker, 'w'):
            pass
        settings = dict(output_root=output_root, identifier=identifier, key=key, deidentification_method=deidentification_method,
                        fields_to_keep=fields_to_keep, groups_to_keep=groups_to_keep, linkage=linkage, run_start=os.stat(marker).st_mtime_ns)

        # DICOM files (detected by content), folder by folder, in one process or in parallel
        folders = iter_dicom_folders(input_folder, single_file)
        if processes > 1 and not single_file:
            print(f"Pseudonymization in {processes} processes...")
            results = run_parallel(folders, processes, pseudonymize_folder, settings, lambda folder, paths: folder_locks(folder, paths, identifier))
        else:
            print("Pseudonymization...")
            results = (pseudonymize_folder(folder, paths, **settings) for folder, paths in folders)

        # merge the results of the folders (linking table always saved, also if an error occurs, so written files stay linked)
        bar = tqdm(unit=' files') if progress_bar else None
        try:
            for result in results:
                merge_records(series_records, result['records'])
                errors.add(result['skipped'], result['failed'])
                number_of_files += result['files'] - len(result['skipped']) - len(result['failed'])
                if bar is not None:
                    bar.update(result['files'])
        except (KeyboardInterrupt, BrokenProcessPool) as error:
            interrupted = 'interrupted' if isinstance(error, KeyboardInterrupt) else f'stopped, a process stopped unexpectedly ({error})'
        finally:
            if bar is not None:
                bar.close()
    finally:
        save_link_table(link_table, series_records, identifier)
        if os.path.exists(marker):
            os.remove(marker)
        release_run_lock(lock)

    # report
    report(series_records, errors.skipped, errors.failed, identifier, f"{number_of_files} file(s) in {len(series_records)} series pseudonymized.", 'Pseudonymization', output_root, link_table,
           skipped_total=errors.skipped_total, failed_total=errors.failed_total, error_log=errors.path)
    if interrupted:
        raise SystemExit(f"Pseudonymization {interrupted}: the linking table contains the folders completed so far; run again to complete it.")

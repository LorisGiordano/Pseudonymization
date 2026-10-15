"""
Locations of input, output, linking table and key file, and structure of the output folder.
"""

""" IMPORTS """

# Pre-installed packages
import os


""" FUNCTIONS """

def is_inside(path: str, folder: str) -> bool:
    """
    Check whether a path is located inside a folder (or is the folder itself).
    """

    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([path, folder]) == folder

def default_output(input_root: str, suffix: str) -> str:
    """
    Get the default output folder next to the input: INPUT_<suffix> (FILE_<suffix> for a single input file).
    """

    return (os.path.splitext(input_root)[0] if os.path.isfile(input_root) else input_root) + suffix

def check_input_output(input_root: str, output_root: str) -> tuple[str, str]:
    """
    Check the locations of input and output: input and output must be separate folders (otherwise original files
    could be overwritten, or outputs processed again in later runs).

    Inputs:
        - input_root: str = path to input folder or single DICOM file
        - output_root: str = path to output folder

    Outputs:
        - input_folder: str = input folder (folder of the file for a single input file)
        - single_file: str = file name of the single input file (None for an input folder)
    """

    if not os.path.exists(input_root):
        raise SystemExit(f"Input '{input_root}' does not exist.")
    single_file = os.path.basename(input_root) if os.path.isfile(input_root) else None
    input_folder = os.path.dirname(os.path.abspath(input_root)) if single_file else input_root
    if single_file:
        if os.path.realpath(output_root) == os.path.realpath(input_folder):
            raise SystemExit(f"The output folder '{output_root}' must differ from the folder of the input file.")
    elif is_inside(output_root, input_folder) or is_inside(input_folder, output_root):
        raise SystemExit(f"The output folder '{output_root}' and the input folder '{input_folder}' must not be located inside each other.")

    return input_folder, single_file

def check_paths(input_root: str, output_root: str, link_table: str, key_file: str = None) -> tuple[str, str]:
    """
    Check the locations of input, output, linking table and key file:
        - input and output must be separate folders (see check_input_output)
        - the key and the linking table must never be stored together with the pseudonymized data

    Inputs:
        - input_root: str = path to input folder or single DICOM file
        - output_root: str = path to output folder
        - link_table: str = path to linking table
        - key_file: str = path to key file (default = None)

    Outputs:
        - input_folder: str = input folder (folder of the file for a single input file)
        - single_file: str = file name of the single input file (None for an input folder)
    """

    input_folder, single_file = check_input_output(input_root, output_root)

    if link_table is None:
        raise SystemExit("No linking table given. Use --link-table PATH (outside the output folder).")
    if is_inside(link_table, output_root):
        raise SystemExit(f"The linking table '{link_table}' must not be located inside the output folder '{output_root}'.")
    if key_file is not None and is_inside(key_file, output_root):
        raise SystemExit(f"The key file '{key_file}' must not be located inside the output folder '{output_root}'.")

    return input_folder, single_file

def series_relative_folder(pseudo_id: str, pseudo_study_uid: str, pseudo_series_uid: str) -> str:
    """
    Build the relative output folder of a series from pseudonymized values only (nothing of the input path is kept,
    as folder and file names can contain identifiers, names or dates):
    <pseudonym (first 32 characters)>/<StudyInstanceUID>/<SeriesInstanceUID>

    Inputs:
        - pseudo_id: str = pseudonym (written in PatientID)
        - pseudo_study_uid: str = pseudonymized StudyInstanceUID ('' if missing)
        - pseudo_series_uid: str = pseudonymized SeriesInstanceUID ('' if missing)

    Outputs:
        - relative_folder: str = relative output folder
    """

    return os.path.join(pseudo_id[:32], pseudo_study_uid or 'unknown_study', pseudo_series_uid or 'unknown_series')

"""
Command line arguments shared by the pseudonymization and extraction commands.
"""

""" IMPORTS """

# Pre-installed packages
import os
import argparse

# Core modules
from .settings import IDENTIFIERS, KEY_ENV_VARIABLE, LINKAGES, profile_descriptions
from .paths import default_output


""" FUNCTIONS """

def base_parser(description: str, output_description: str, output_suffix: str) -> argparse.ArgumentParser:
    """
    Create an argument parser with the arguments shared by all commands (input, output, profile, identifier,
    linkage, linking table, key file).

    Inputs:
        - description: str = description of the command
        - output_description: str = description of the output
        - output_suffix: str = suffix of the default output folder (INPUT<suffix>)

    Outputs:
        - parser: argparse.ArgumentParser = argument parser
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('input', type=str, help='Path to the root folder containing DICOM files (detected by content, with or without .dcm extension), or to a single DICOM file.')
    parser.add_argument('--output', '-o', type=str, default=None, help=f'Path to output folder where to save {output_description}, outside the input folder (default = INPUT{output_suffix} next to the input).')
    parser.add_argument('--profile', '-p', type=int, default=1, help=f'Selected profile ({profile_descriptions()}).')
    parser.add_argument('--identifier', '-i', type=str, default='PatientID', choices=list(IDENTIFIERS), help='Identifier to be pseudonymized and used for the linking table (default = PatientID).')
    parser.add_argument('--linkage', type=str, default='patient', choices=list(LINKAGES), help="Linkage level of the pseudonyms: 'patient' = studies of the same patient share the pseudonym (default), 'study' = one pseudonym per study, studies of the same patient cannot be linked without the key/linking table.")
    parser.add_argument('--link-table', '-l', type=str, required=True, help='Path to the linking table (.xlsx or .csv) between original and pseudo identifiers, one row per DICOM series. Must be outside the output folder; existing tables are updated.')
    parser.add_argument('--key-file', '-k', type=str, default=None, help=f'Path to the secret key file used to compute the pseudonyms (created if it does not exist; keep it outside the output folder). If not given, the key is read from the environment variable {KEY_ENV_VARIABLE}.')
    parser.set_defaults(output_suffix=output_suffix)
    return parser

def input_output(args: argparse.Namespace) -> tuple[str, str]:
    """
    Get the input (folder or single DICOM file) and output folder from the parsed arguments.

    Inputs:
        - args: argparse.Namespace = parsed arguments (see base_parser)

    Outputs:
        - input_root: str = path to input folder or single DICOM file
        - output_root: str = path to output folder
    """

    input_root = os.path.normpath(args.input)
    output_root = args.output if args.output is not None else default_output(input_root, args.output_suffix)
    return input_root, output_root

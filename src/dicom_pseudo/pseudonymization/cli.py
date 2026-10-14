""" IMPORTS """

# Pre-installed packages
import os
import argparse

# Pseudonymization modules
from .settings import IDENTIFIERS, KEY_ENV_VARIABLE, LINKAGES, profile_descriptions
from .pipeline import pseudonymization


""" MAIN """

def main() -> None:
    """
    CLI entry point. Parse arguments then run pseudonymization workflow.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help='Path to the root folder containing DICOM files (detected by content, with or without .dcm extension), or to a single DICOM file.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Path to output folder where to save pseudonymized DICOM files, outside the input folder (default = INPUT_pseudonymized next to the input).')
    parser.add_argument('--profile', '-p', type=int, default=1, help=f'Selected profile ({profile_descriptions()}).')
    parser.add_argument('--identifier', '-i', type=str, default='PatientID', choices=list(IDENTIFIERS), help='Identifier to be pseudonymized and used for the linking table (default = PatientID).')
    parser.add_argument('--linkage', type=str, default='patient', choices=list(LINKAGES), help="Linkage level of the pseudonyms: 'patient' = studies of the same patient share the pseudonym (default), 'study' = one pseudonym per study, studies of the same patient cannot be linked without the key/linking table.")
    parser.add_argument('--link-table', '-l', type=str, required=True, help='Path to the linking table (.xlsx or .csv) between original and pseudo identifiers, one row per DICOM series. Must be outside the output folder; existing tables are updated.')
    parser.add_argument('--key-file', '-k', type=str, default=None, help=f'Path to the secret key file used to compute the pseudonyms (created if it does not exist; keep it outside the output folder). If not given, the key is read from the environment variable {KEY_ENV_VARIABLE}.')
    args = parser.parse_args()

    # Input root (folder or single DICOM file)
    input_root = os.path.normpath(args.input)

    # Output root (default next to the input: FOLDER_pseudonymized, or FILE_pseudonymized for a single file)
    output_root = args.output
    if output_root is None:
        output_root = os.path.splitext(input_root)[0] if os.path.isfile(input_root) else input_root
        output_root += '_pseudonymized'

    # Profile
    profile = args.profile

    # Identifier
    identifier = args.identifier

    # Key file
    key_file = args.key_file

    # Linking table
    link_table = args.link_table

    # Linkage
    linkage = args.linkage

    # Pseudonymization
    pseudonymization(input_root, output_root, profile, identifier, key_file=key_file, link_table=link_table, linkage=linkage)


# python -m dicom_pseudo.pseudonymization INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -l LINK_TABLE -k KEY_FILE

if __name__ == '__main__':

    main()

""" IMPORTS """

# Pre-installed packages
import os
import argparse

# Pseudonymization modules
from .settings import KEY_ENV_VARIABLE, profile_descriptions
from .pipeline import pseudonymization


""" MAIN """

def main() -> None:
    """
    CLI entry point. Parse arguments then run pseudonymization workflow.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help='Path to the root folder containing DICOM files.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Path to output folder where to save pseudonymized DICOM files.')
    parser.add_argument('--profile', '-p', type=int, default=1, help=f'Selected profile ({profile_descriptions()}).')
    parser.add_argument('--identifier', '-i', type=str, default='StudyID', help='Identifier to be used for linking table (PatientID, StudyID, AgfaID/AccessionNumber).')
    parser.add_argument('--link-table', '-l', type=str, required=True, help='Path to the linking table (.xlsx or .csv) between original and pseudo identifiers, one row per DICOM series. Must be outside the output folder; existing tables are updated.')
    parser.add_argument('--key-file', '-k', type=str, default=None, help=f'Path to the secret key file used to compute the pseudonyms (created if it does not exist; keep it outside the output folder). If not given, the key is read from the environment variable {KEY_ENV_VARIABLE}.')
    args = parser.parse_args()

    # Input root
    input_root = args.input
    if '.dcm' in input_root:
        input_root = os.path.dirname(os.path.abspath(input_root))

    # Output root
    output_root = args.output
    if output_root is None:
        output_root = input_root + '_pseudonymized'
    output_root = output_root.replace(' ', '')

    # Profile
    profile = args.profile

    # Identifier
    identifier = args.identifier

    # Key file
    key_file = args.key_file

    # Linking table
    link_table = args.link_table

    # Pseudonymization
    pseudonymization(input_root, output_root, profile, identifier, key_file=key_file, link_table=link_table)


# python -m dicom_pseudo.pseudonymization INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -l LINK_TABLE -k KEY_FILE

if __name__ == '__main__':

    main()

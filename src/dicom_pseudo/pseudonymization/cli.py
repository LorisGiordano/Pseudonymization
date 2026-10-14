"""
Command line interface of the pseudonymization.
"""

""" IMPORTS """

# Core modules
from ..core.cli import base_parser, input_output

# Pseudonymization modules
from .pipeline import pseudonymization


""" MAIN """

def main() -> None:
    """
    CLI entry point. Parse arguments then run pseudonymization workflow.
    """

    parser = base_parser('Pseudonymize DICOM files.', 'pseudonymized DICOM files', '_pseudonymized')
    args = parser.parse_args()
    input_root, output_root = input_output(args)
    pseudonymization(input_root, output_root, args.profile, args.identifier, key_file=args.key_file, link_table=args.link_table, linkage=args.linkage)


# pseudonymize INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER --linkage LINKAGE -l LINK_TABLE -k KEY_FILE

if __name__ == '__main__':

    main()

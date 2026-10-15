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
    parser.add_argument('--processes', '-n', type=int, default=1, help='Number of processes: 0 or 1 = one process (default), more = folders pseudonymized in parallel (one task per input folder; folders sharing a patient, study or series are never processed at the same time).')
    args = parser.parse_args()
    input_root, output_root = input_output(args)
    pseudonymization(input_root, output_root, args.profile, args.identifier, key_file=args.key_file, link_table=args.link_table, linkage=args.linkage, processes=args.processes)


# pseudonymize INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER --linkage LINKAGE -l LINK_TABLE -k KEY_FILE -n PROCESSES

if __name__ == '__main__':

    main()

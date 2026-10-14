"""
Command line interface of the extraction.
"""

""" IMPORTS """

# Core modules
from ..core.cli import base_parser, input_output

# Extraction modules
from .timepoints import TIME_STAMP_FIELDS
from .pipeline import extraction


""" MAIN """

def main() -> None:
    """
    CLI entry point. Parse arguments then run extraction workflow.
    """

    parser = base_parser('Extract pseudonymized NifTi images and metadata from DICOM files.', 'pseudonymized NifTi files', '_extracted')
    parser.add_argument('--timestamp', '-t', type=str, default=None, choices=list(TIME_STAMP_FIELDS), help='DICOM keyword to be used for 4D data reconstruction with profile 3 (default = automatic detection).')
    args = parser.parse_args()
    input_root, output_root = input_output(args)
    extraction(input_root, output_root, args.profile, args.identifier, args.timestamp, key_file=args.key_file, link_table=args.link_table, linkage=args.linkage)


# extract INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -t TIMESTAMP --linkage LINKAGE -l LINK_TABLE -k KEY_FILE

if __name__ == '__main__':

    main()

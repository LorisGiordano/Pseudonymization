"""
Command line interface of the extraction.
"""

""" IMPORTS """

# Core modules
from ..core.cli import io_parser, add_profile_argument, input_output

# Extraction modules
from .timepoints import TIME_STAMP_FIELDS
from .pipeline import extraction


""" MAIN """

def main() -> None:
    """
    CLI entry point. Parse arguments then run extraction workflow.
    """

    parser = io_parser('Extract NifTi images and metadata from DICOM files (meant for pseudonymized DICOM files), reproducing the structure of the input folder.',
                       'NifTi files', '_extracted')
    add_profile_argument(parser)
    parser.add_argument('--timestamp', '-t', type=str, default=None, choices=list(TIME_STAMP_FIELDS), help='DICOM keyword giving the time points of 4D series (default = automatic detection).')
    args = parser.parse_args()
    input_root, output_root = input_output(args)
    extraction(input_root, output_root, args.profile, args.timestamp)


# extract INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -t TIMESTAMP

if __name__ == '__main__':

    main()

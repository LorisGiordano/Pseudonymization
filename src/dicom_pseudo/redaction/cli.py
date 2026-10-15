"""
Command line interface of the redaction.
"""

""" IMPORTS """

# Core modules
from ..core.cli import io_parser, input_output

# Redaction modules
from .pipeline import FILLS, redaction


""" MAIN """

def main() -> None:
    """
    CLI entry point. Parse arguments then run redaction workflow.
    """

    parser = io_parser('Redact text burned into the pixel data of (pseudonymized) DICOM files.', 'redacted DICOM files', '_redacted')
    parser.add_argument('--fill', '-f', type=str, default='contrast', choices=list(FILLS), help="Fill of the redaction boxes: 'contrast' (default) or 'background'.")
    parser.add_argument('--padding', type=int, default=25, help='Padding (pixels) around the image for the text detection (default = 25).')
    args = parser.parse_args()
    input_root, output_root = input_output(args)
    redaction(input_root, output_root, args.fill, args.padding)


# redact INPUT_ROOT -o OUTPUT_ROOT -f FILL

if __name__ == '__main__':

    main()

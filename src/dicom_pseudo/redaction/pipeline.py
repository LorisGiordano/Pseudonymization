"""
Redaction of text burned into the pixel data of DICOM files (Microsoft Presidio image redactor: OCR + PHI detection).
Meant to be run on pseudonymized DICOM files: the files are copied with the same relative paths, only the pixel data
is changed.
"""

""" IMPORTS """

# Pre-installed packages
import os

# Tqdm [optional]
try:
    from tqdm import tqdm
    PROGRESS_BAR = True
except:
    print("INFO: Progress bar not available because tqdm is not installed.")
    PROGRESS_BAR = False

# Pydicom
import pydicom

# Core modules
from ..core.files import find_dicom_files, save_dicom
from ..core.paths import check_input_output
from ..core.report import report


""" DEFINITIONS """

# Fill of the redaction boxes: 'contrast' (color contrasting the image) or 'background' (background color)
FILLS = ('contrast', 'background')

# Installation of the optional redaction dependencies
INSTALL_MESSAGE = ("Redaction requires Microsoft Presidio: pip install 'dicom_pseudo[presidio]', "
                   "python -m spacy download en_core_web_lg, and the Tesseract OCR engine (e.g. brew install tesseract).")


""" FUNCTIONS """

def load_engine():
    """
    Load the Presidio DICOM image redactor engine (optional dependency).

    Outputs:
        - engine: presidio_image_redactor.DicomImageRedactorEngine = redactor engine
    """

    try:
        from presidio_image_redactor import DicomImageRedactorEngine
    except ImportError:
        raise SystemExit(INSTALL_MESSAGE)
    try:
        return DicomImageRedactorEngine()
    except Exception as error:
        raise SystemExit(f"Redaction engine could not be loaded ({type(error).__name__}: {error}). {INSTALL_MESSAGE}")

def redact_dicom(engine, input_path: str, output_path: str, fill: str = 'contrast', padding_width: int = 25) -> None:
    """
    Redact the text burned into the pixel data of a DICOM file.

    Inputs:
        - engine: presidio_image_redactor.DicomImageRedactorEngine = redactor engine
        - input_path: str = path to DICOM file
        - output_path: str = path to output DICOM file
        - fill: str = fill of the redaction boxes ('contrast' or 'background') (default = 'contrast')
        - padding_width: int = padding (pixels) around the image for the text detection (default = 25)
    """

    dicom_data = pydicom.dcmread(input_path, force=True)
    if 'PixelData' not in dicom_data:
        raise ValueError("no pixel data")
    redacted = engine.redact(dicom_data, fill=fill, padding_width=padding_width)
    save_dicom(redacted, output_path)

def redaction(input_root: str, output_root: str, fill: str = 'contrast', padding_width: int = 25, progress_bar: bool = PROGRESS_BAR) -> None:
    """
    Main function to redact the text burned into the pixel data of a DICOM directory (or a single DICOM file).

    Inputs:
        - input_root: str = path to root of all DICOM folders (or to a single DICOM file)
        - output_root: str = path to output folder (same relative paths as the input)
        - fill: str = fill of the redaction boxes ('contrast' or 'background') (default = 'contrast')
        - padding_width: int = padding (pixels) around the image for the text detection (default = 25)
        - progress_bar: bool = (default = PROGRESS_BAR)
    """

    # check inputs and locations before doing anything, load the engine
    if fill not in FILLS:
        raise SystemExit(f"Fill '{fill}' not supported. (Use one of: {', '.join(FILLS)})")
    input_folder, single_file = check_input_output(input_root, output_root)
    engine = load_engine()
    os.makedirs(output_root, exist_ok=True)

    # DICOM files (detected by content)
    dicom_files = find_dicom_files(input_folder, single_file)
    print(f"Redaction of {len(dicom_files)} DICOM files...")

    # redact all files, same relative paths as the input
    failed = []
    for input_path in (tqdm(dicom_files) if progress_bar else dicom_files):
        output_path = os.path.join(output_root, os.path.relpath(input_path, input_folder))
        try:
            redact_dicom(engine, input_path, output_path, fill, padding_width)
        except Exception as error:
            failed.append((input_path, f'{type(error).__name__}: {error}'))

    # report
    report({}, [], failed, '', f"{len(dicom_files) - len(failed)} file(s) redacted.", 'Redaction', output_root)

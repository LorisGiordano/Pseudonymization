"""
Pseudonymization of DICOM datasets (pseudonymized DICOM files).

Modules:
    - deidentification: pseudonym and de-identification flags, pseudonymized UIDs written in a dataset
    - sanitization: removal/emptying of the fields that are not kept, private tags and file meta information
    - pipeline: pseudonymization of DICOM files
    - cli: command line interface

Shared modules (settings, pseudonyms, identity, files, paths, linking table, report) are in dicom_pseudo.core.
"""

from .pipeline import pseudonymization
from .cli import main

__all__ = ['pseudonymization', 'main']

"""
Redaction of text burned into the pixel data of (pseudonymized) DICOM files, with Microsoft Presidio
(optional dependency: pip install 'dicom_pseudo[presidio]').

Modules:
    - pipeline: redaction of DICOM files
    - cli: command line interface

Shared modules (files, paths, report) are in dicom_pseudo.core.
"""

from .pipeline import redaction
from .cli import main

__all__ = ['redaction', 'main']

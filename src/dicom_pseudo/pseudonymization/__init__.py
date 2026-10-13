"""
Pseudonymization of DICOM datasets.

Modules:
    - settings: configuration (tags, groups, identifiers, profiles) loaded from the JSON files in config/
    - pseudonym: secret key, pseudonyms of identifiers and UIDs
    - sanitization: removal/emptying of the fields that are not kept, private tags and file meta information
    - linking_table: linking table between original and pseudo identifiers
    - pipeline: pseudonymization of DICOM files and folders
    - cli: command line interface
"""

from .pipeline import pseudonymization
from .cli import main

__all__ = ['pseudonymization', 'main']

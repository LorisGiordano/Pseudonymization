"""
Core modules shared by pseudonymization and extraction.

Modules:
    - settings: configuration (tags, groups, identifiers, profiles) loaded from the JSON files in config/
    - pseudonym: secret key and keyed hashes for pseudonyms and pseudonymized UIDs
    - identity: original and pseudonymized identification of a DICOM series
    - files: discovery of DICOM files (detected by content) and grouping by series
    - paths: checks of input/output/linking table/key locations, structure of the output folder
    - linking_table: linking table between original and pseudonymized identifiers
    - tables: reading and writing of tables (.xlsx/.csv) that open correctly in spreadsheet applications
    - report: warnings and summary of a run
    - cli: command line arguments shared by the commands
"""

"""
Extraction of pseudonymized NifTi images and metadata from DICOM datasets.

Modules:
    - timepoints: detection of the time points of a series (4D data)
    - nifti: conversion of a series to NifTi (3D/4D with dicom2nifti, 2D images)
    - metadata: metadata of the profile stored with the images
    - pipeline: extraction of DICOM series
    - cli: command line interface

Shared modules (settings, pseudonyms, identity, files, paths, linking table, report) are in dicom_pseudo.core.
"""

from .pipeline import extraction
from .cli import main

__all__ = ['extraction', 'main']

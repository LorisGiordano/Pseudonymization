#!/usr/bin/env bash
# Pseudonymize a DICOM folder and extract NifTi images from the pseudonymized files, from the command line.
#
# usage: bash examples/01_command_line.sh DICOM_FOLDER WORK_FOLDER
#
# WORK_FOLDER/
#   secrets/               key and linking tables: keep separate, never share with the data
#   release/dicom/         pseudonymized DICOM files (profile 1)
#   release/nifti/         NifTi images and metadata, same folder structure as release/dicom
#   release/dicom_4d/      pseudonymized DICOM files keeping the temporal fields (profile 3)
#   release/nifti_4d/      4D NifTi images (one per time point), same folder structure as release/dicom_4d
set -euo pipefail

DICOM_FOLDER="$1"
WORK_FOLDER="$2"
SECRETS="$WORK_FOLDER/secrets"
RELEASE="$WORK_FOLDER/release"

# 1. pseudonymized DICOM files: demographics kept (profile 1), one pseudonym per patient (default)
#    the key file is created at the first run, keep it to obtain the same pseudonyms in later runs
pseudonymize "$DICOM_FOLDER" \
    --output "$RELEASE/dicom" \
    --profile 1 \
    --identifier PatientID \
    --key-file "$SECRETS/project.key" \
    --link-table "$SECRETS/linking_table.xlsx"

# 2. NifTi images and metadata from the pseudonymized files: no key or linking table needed, same folder structure
extract "$RELEASE/dicom" \
    --output "$RELEASE/nifti" \
    --profile 1

# 3. 4D data (e.g. fMRI, dynamic PET): pseudonymize with profile 3 to keep the temporal fields, then extract with
#    profile 3, one NifTi per time point (time points detected automatically, or forced with --timestamp KEYWORD)
pseudonymize "$DICOM_FOLDER" \
    --output "$RELEASE/dicom_4d" \
    --profile 3 \
    --key-file "$SECRETS/project.key" \
    --link-table "$SECRETS/linking_table_4d.xlsx"
extract "$RELEASE/dicom_4d" \
    --output "$RELEASE/nifti_4d" \
    --profile 3

# 4. optional: redact text burned into the pixel data of the pseudonymized files (pip install 'dicom_pseudo[presidio]')
# redact "$RELEASE/dicom" --output "$RELEASE/dicom_redacted" --fill contrast

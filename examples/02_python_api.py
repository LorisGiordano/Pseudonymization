"""
Pseudonymize a DICOM folder and extract NifTi images with the Python API, then summarize the linking table.

usage: python examples/02_python_api.py DICOM_FOLDER WORK_FOLDER
"""

import os
import sys

import pandas as pd

from dicom_pseudo.pseudonymization import pseudonymization
from dicom_pseudo.extraction import extraction


dicom_folder, work_folder = sys.argv[1], sys.argv[2]
secrets = os.path.join(work_folder, 'secrets')          # key and linking tables, never shared with the data
release = os.path.join(work_folder, 'release')          # data to share
key_file = os.path.join(secrets, 'project.key')

# pseudonymized DICOM files (profile 1: demographics kept)
pseudonymization(
    input_root=dicom_folder,
    output_root=os.path.join(release, 'dicom'),
    profile=1,
    identifier='PatientID',
    key_file=key_file,
    link_table=os.path.join(secrets, 'linking_table.xlsx'),
    linkage='patient',
)

# pseudonymized NifTi images and metadata (same key: same pseudonyms and output folders)
extraction(
    input_root=dicom_folder,
    output_root=os.path.join(release, 'nifti'),
    profile=1,
    identifier='PatientID',
    key_file=key_file,
    link_table=os.path.join(secrets, 'linking_table_nifti.xlsx'),
)

# linking table: one row per series, original and pseudonymized identifiers
table = pd.read_excel(os.path.join(secrets, 'linking_table.xlsx'), dtype=str)
print(f"\n{table['Original PatientID'].nunique()} patients, {table['Original StudyInstanceUID'].nunique()} studies, "
      f"{len(table)} series, {table['Number of files'].astype(int).sum()} files")
print(table[['Pseudonym PatientID', 'Modality', 'SeriesDescription', 'Number of files', 'Output folder']].head(10).to_string(index=False))

# NifTi overview (no original identifiers): released together with the images
metadata = pd.read_excel(os.path.join(release, 'nifti', 'metadata.xlsx'))
print(f"\nNifTi series: {len(metadata)}; columns: {list(metadata.columns)}")

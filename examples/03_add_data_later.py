"""
Pseudonymize a cohort in several batches (e.g. new patients or follow-up studies arriving later): with the same key and
linking table, a patient gets the same pseudonym in every batch, and the linking table is updated.

usage: python examples/03_add_data_later.py BATCH_FOLDER [BATCH_FOLDER ...] WORK_FOLDER
"""

import os
import sys

import pandas as pd

from dicom_pseudo.pseudonymization import pseudonymization


*batches, work_folder = sys.argv[1:]
key_file = os.path.join(work_folder, 'secrets', 'project.key')
link_table = os.path.join(work_folder, 'secrets', 'linking_table.csv')

for batch in batches:
    print(f"\n=== batch {batch}")
    pseudonymization(batch, os.path.join(work_folder, 'release', 'dicom'), profile=1, identifier='PatientID',
                     key_file=key_file, link_table=link_table, progress_bar=False)

# same patient -> same pseudonym, whatever the batch
table = pd.read_csv(link_table, dtype=str)
pseudonyms_per_patient = table.groupby('Original PatientID')['Pseudonym PatientID'].nunique()
print(f"\n{len(table)} series of {len(pseudonyms_per_patient)} patients in the linking table; "
      f"patients with more than one pseudonym: {int((pseudonyms_per_patient > 1).sum())}")

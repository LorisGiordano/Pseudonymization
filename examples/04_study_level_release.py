"""
Study-level release: studies of the same patient cannot be linked in the released data (one pseudonym per study, UIDs
mapped per study), machine information kept (profile 4). The key holder can still link the studies to their patient
with the linking table (or recompute the patient pseudonym with the key).

usage: python examples/04_study_level_release.py DICOM_FOLDER WORK_FOLDER
"""

import os
import sys

import pandas as pd

from dicom_pseudo.pseudonymization import pseudonymization
from dicom_pseudo.core.pseudonym import load_key, pseudonym


dicom_folder, work_folder = sys.argv[1], sys.argv[2]
key_file = os.path.join(work_folder, 'secrets', 'project.key')
link_table = os.path.join(work_folder, 'secrets', 'linking_table_study_level.xlsx')

pseudonymization(dicom_folder, os.path.join(work_folder, 'release', 'dicom_study_level'), profile=4, identifier='PatientID',
                 key_file=key_file, link_table=link_table, linkage='study')

# released data: one pseudonym per study; linking table: patient pseudonym of each study (key holder only)
table = pd.read_excel(link_table, dtype=str)
studies = table.drop_duplicates('Original StudyInstanceUID')
print(f"\n{studies['Pseudonym PatientID'].nunique()} study pseudonyms in the released data, "
      f"{studies['Patient pseudonym PatientID'].nunique()} patients for the key holder")

# key holder: the patient pseudonym can be recomputed from the original identifier and the key
key = load_key(key_file)
row = studies.iloc[0]
assert pseudonym(row['Original PatientID'], key) == row['Patient pseudonym PatientID']
print("patient pseudonym recomputed from the key: OK")

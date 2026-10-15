"""
De-identification of a DICOM dataset: pseudonym and de-identification flags, pseudonymized UIDs.
"""

""" IMPORTS """

# Pydicom
import pydicom

# Core modules
from ..core.settings import UIDS_NOT_REMAPPED
from ..core.pseudonym import remap_uid
from ..core.identity import SeriesIdentity


""" FUNCTIONS """

def write_pseudonym(dicom_data: pydicom.dataset.Dataset, identity: SeriesIdentity, deidentification_method: str = '') -> None:
    """
    Blank the original identifier, write the pseudonym in PatientID and PatientName (so images can be linked via
    the linking table), and flag the dataset as de-identified (DICOM PS3.15 Annex E).

    Inputs:
        - dicom_data: pydicom.dataset.Dataset = dicom file object to modify in place
        - identity: SeriesIdentity = identity of the series (see core.identity.identify)
        - deidentification_method: str = description stored in DeidentificationMethod (default = '')
    """

    dicom_data[identity.identifier_tag].value = ''
    dicom_data.PatientID = identity.pseudo_id
    dicom_data.PatientName = identity.pseudo_id
    dicom_data.PatientIdentityRemoved = 'YES'
    dicom_data.DeidentificationMethod = deidentification_method

def remap_uids(dataset: pydicom.dataset.Dataset, key: bytes, scope: str = '', uids_not_remapped: set = UIDS_NOT_REMAPPED) -> None:
    """
    Replace all instance UIDs of a dataset (including those nested in sequences, e.g. references to other
    instances, series or frames of reference) by their pseudonymized UIDs. Well-known UIDs (SOP classes,
    transfer syntaxes, ...) are kept.

    Inputs:
        - dataset: pydicom.dataset.Dataset = dataset to modify in place
        - key: bytes = secret key
        - scope: str = scope of the UID mapping (default = '' => global, see core.pseudonym.pseudo_uid)
        - uids_not_remapped: set = keywords of UID attributes to keep (default = UIDS_NOT_REMAPPED)
    """

    for elem in dataset.iterall():
        if elem.VR != 'UI' or elem.keyword in uids_not_remapped or elem.value in (None, ''):
            continue
        if elem.VM > 1:
            elem.value = [remap_uid(uid, key, scope) for uid in elem.value]
        else:
            elem.value = remap_uid(elem.value, key, scope)

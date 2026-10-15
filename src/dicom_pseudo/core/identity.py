"""
Identity of a DICOM series: original identifier and UIDs, and their pseudonymized counterparts. Computed in one place
for pseudonymization and extraction, so that both give the same pseudonyms, UIDs and output folders.
"""

""" IMPORTS """

# Pre-installed packages
from dataclasses import dataclass

# Pydicom
import pydicom
from pydicom.tag import Tag

# Core modules
from .settings import IDENTIFIERS, LINKAGES
from .pseudonym import compute_pseudonyms, remap_uid
from .paths import series_relative_folder


""" SERIES IDENTITY """

@dataclass(frozen=True)
class SeriesIdentity:
    """
    Original and pseudonymized identification of a DICOM series.

    Attributes:
        - identifier: str = name of the identifier (e.g. PatientID)
        - identifier_tag: Tag = tag in which the identifier value was found
        - original_id: str = original identifier value
        - pseudo_id: str = pseudonym written in the data (patient- or study-level, according to the linkage)
        - patient_pseudo_id: str = patient-level pseudonym (only stored in the linking table)
        - linkage: str = 'patient' or 'study'
        - original_study_uid, original_series_uid: str = original UIDs ('' if missing)
        - pseudo_study_uid, pseudo_series_uid: str = pseudonymized UIDs ('' if missing)
    """

    identifier: str
    identifier_tag: Tag
    original_id: str
    pseudo_id: str
    patient_pseudo_id: str
    linkage: str
    original_study_uid: str
    original_series_uid: str
    pseudo_study_uid: str
    pseudo_series_uid: str

    @property
    def uid_scope(self) -> str:
        """
        Scope of the UID mapping: global for patient-level linkage, per study for study-level linkage (so that UIDs
        shared between studies of the same patient are replaced differently in each study).
        """

        return self.original_study_uid if self.linkage == 'study' else ''

    @property
    def output_folder(self) -> str:
        """
        Relative output folder of the series: <pseudonym[:16]>/<StudyInstanceUID>/<SeriesInstanceUID>.
        """

        return series_relative_folder(self.pseudo_id, self.pseudo_study_uid, self.pseudo_series_uid)


""" FUNCTIONS """

def get_identifier_value(dicom_data: pydicom.dataset.Dataset, identifier: str, identifiers: dict = IDENTIFIERS) -> tuple[str, Tag]:
    """
    Get the value of the chosen identifier from the first candidate tag that holds a non-empty value.

    Inputs:
        - dicom_data: pydicom.dataset.Dataset = dicom file object (in which the identifier is present)
        - identifier: str = name of the identifier (key of identifiers)
        - identifiers: dict = candidate tags for each identifier (default = IDENTIFIERS)

    Outputs:
        - value: str = identifier value (None if not found)
        - tag: Tag = tag in which the identifier value was found (None if not found)
    """

    if identifier not in identifiers:
        raise SystemExit(f"Identifier '{identifier}' not supported. (Use one of: {', '.join(identifiers)})")

    for tag in identifiers[identifier]:
        element = dicom_data.get(Tag(tag), None)
        if element is None or element.value is None:
            continue
        value = element.value
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        value = str(value).strip(' \x00')
        if value:
            return value, Tag(tag)

    return None, None

def identify(dicom_data: pydicom.dataset.Dataset, identifier: str, key: bytes, linkage: str = 'patient') -> SeriesIdentity:
    """
    Compute the identity of the series of a DICOM dataset (original, not yet pseudonymized).

    Inputs:
        - dicom_data: pydicom.dataset.Dataset = original dicom file object
        - identifier: str = name of the identifier (key of IDENTIFIERS)
        - key: bytes = secret key
        - linkage: str = 'patient' or 'study' level pseudonyms (default = 'patient')

    Outputs:
        - identity: SeriesIdentity = identity of the series (None if the identifier is missing)
    """

    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")

    original_id, identifier_tag = get_identifier_value(dicom_data, identifier)
    if original_id is None:
        return None

    original_study_uid = str(dicom_data.get('StudyInstanceUID', ''))
    original_series_uid = str(dicom_data.get('SeriesInstanceUID', ''))
    pseudo_id, patient_pseudo_id = compute_pseudonyms(original_id, original_study_uid, key, linkage)
    scope = original_study_uid if linkage == 'study' else ''

    return SeriesIdentity(
        identifier=identifier,
        identifier_tag=identifier_tag,
        original_id=original_id,
        pseudo_id=pseudo_id,
        patient_pseudo_id=patient_pseudo_id,
        linkage=linkage,
        original_study_uid=original_study_uid,
        original_series_uid=original_series_uid,
        pseudo_study_uid=remap_uid(original_study_uid, key, scope),
        pseudo_series_uid=remap_uid(original_series_uid, key, scope),
    )

"""
Removal or emptying of the DICOM fields that are not kept, private tags and file meta information.
"""

""" IMPORTS """

# Pydicom
import pydicom
from pydicom.dataset import FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID

# Core modules
from ..core.settings import FILE_META_TO_KEEP, REPEATING_GROUPS_TO_REMOVE


""" FUNCTIONS """

def remove_private_tags(dataset: pydicom.dataset.Dataset, tags_to_keep: set[Tag]) -> None:
    """
    Recursively remove all private elements, except the private elements to keep and their private creators.

    Inputs:
        - dataset: pydicom.dataset.Dataset = dataset to modify in place
        - tags_to_keep: set[Tag] = tags of the elements to keep
    """

    def remove(dataset, elem):
        # private creators are only kept if one of their private elements to keep is present
        private_creators_to_keep = {Tag(tag.group, tag.element >> 8) for tag in tags_to_keep if tag.is_private and tag in dataset}
        if elem.tag.is_private and elem.tag not in tags_to_keep and elem.tag not in private_creators_to_keep:
            del dataset[elem.tag]

    dataset.walk(remove)

def has_content(dataset: pydicom.dataset.Dataset) -> bool:
    """
    Check whether a dataset still holds any non-empty value.

    Inputs:
        - dataset: pydicom.dataset.Dataset = dataset to check

    Outputs:
        - has_content: bool = whether any element has a non-empty value
    """

    for elem in dataset:
        if elem.VR == 'SQ':
            if len(elem.value) > 0:
                return True
        elif elem.value not in (None, '', b''):
            return True
    return False

def sanitize_dataset(dataset: pydicom.dataset.Dataset, tags_to_keep: set[Tag], groups_to_keep: set[int], repeating_groups_to_remove: tuple = REPEATING_GROUPS_TO_REMOVE) -> None:
    """
    Recursively sanitize a dataset without removing structural tags:
        - elements to keep are kept as is (including the full content of sequences to keep), as well as the
          private creators remaining after remove_private_tags
        - UIDs are kept, as they are already pseudonymized (or well-known class/syntax UIDs), so that
          references to other instances remain valid
        - other sequences are sanitized recursively keeping only their UIDs (fields to keep only apply at
          the top level, e.g. PatientID in OtherPatientIDsSequence is not kept), items without remaining
          content are removed
        - repeating groups (overlays, curves) are removed, as they can hold burned-in annotations
        - values of all other elements are emptied (zero-length values, valid for type 2 attributes)

    Inputs:
        - dataset: pydicom.dataset.Dataset = dataset to modify in place
        - tags_to_keep: set[Tag] = tags of the elements to keep
        - groups_to_keep: set[int] = groups of the elements to keep
        - repeating_groups_to_remove: tuple = ranges of repeating groups to remove (default = REPEATING_GROUPS_TO_REMOVE)
    """

    for tag in list(dataset.keys()):
        elem = dataset[tag]

        if elem.tag in tags_to_keep or elem.tag.group in groups_to_keep or elem.VR == 'UI' or elem.tag.is_private_creator:
            continue

        if any(elem.tag.group in groups for groups in repeating_groups_to_remove):
            del dataset[tag]
        elif elem.VR == 'SQ':
            for item in elem.value:
                sanitize_dataset(item, set(), set(), repeating_groups_to_remove)
            elem.value = Sequence([item for item in elem.value if has_content(item)])
        else:
            elem.value = None

def ensure_file_meta(dicom_data: pydicom.dataset.FileDataset, file_meta_to_keep: set = FILE_META_TO_KEEP) -> None:
    """
    Keep file meta information synchronized with the dataset content, and remove all file meta elements that
    are not required (e.g. Source/Sending/Receiving AE Titles, which can identify the station).

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object to modify in place
        - file_meta_to_keep: set = tags of the file meta elements to keep (default = FILE_META_TO_KEEP)
    """

    if dicom_data.file_meta is None:
        dicom_data.file_meta = FileMetaDataset()

    for tag in list(dicom_data.file_meta.keys()):
        if tag not in file_meta_to_keep:
            del dicom_data.file_meta[tag]

    dicom_data.file_meta.MediaStorageSOPClassUID = dicom_data.SOPClassUID
    dicom_data.file_meta.MediaStorageSOPInstanceUID = dicom_data.SOPInstanceUID
    dicom_data.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    dicom_data.file_meta.ImplementationVersionName = f'PYDICOM {pydicom.__version__}'[:16]

    if 'TransferSyntaxUID' not in dicom_data.file_meta:
        dicom_data.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

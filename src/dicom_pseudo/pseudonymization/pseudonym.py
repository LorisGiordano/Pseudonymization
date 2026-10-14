""" IMPORTS """

# Pre-installed packages
import os
import hashlib
import hmac
import secrets

# Pydicom
import pydicom
from pydicom.tag import Tag
from pydicom.uid import UID_dictionary

# Settings
from .settings import IDENTIFIERS, KEY_ENV_VARIABLE, LINKAGES, UIDS_NOT_REMAPPED


""" SECRET KEY """

def load_key(key_file: str = None, key_env_variable: str = KEY_ENV_VARIABLE) -> bytes:
    """
    Load the secret key used to compute the pseudonyms (HMAC-SHA256).

    The key is read from the key file if given (a new random key is created if the file does not exist yet),
    otherwise from the environment variable. Without the key, pseudonyms cannot be recomputed or reversed by
    brute-forcing the (low-entropy) original identifiers, so the key must be stored securely and separately
    from the pseudonymized data.

    Inputs:
        - key_file: str = path to file containing the secret key (default = None)
        - key_env_variable: str = name of environment variable containing the secret key (default = KEY_ENV_VARIABLE)

    Outputs:
        - key: bytes = secret key
    """

    # read key from key file, or create a new random key file
    if key_file is not None:
        if os.path.exists(key_file):
            with open(key_file, 'r') as file:
                key = file.read().strip()
        else:
            key = secrets.token_hex(32)
            os.makedirs(os.path.dirname(os.path.abspath(key_file)), exist_ok=True)
            file_descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(file_descriptor, 'w') as file:
                file.write(key + '\n')
            print(f"WARNING: New pseudonymization key created at '{key_file}'. "
                  "Keep it secret, back it up, and never share it together with the pseudonymized data. "
                  "The same key is required to obtain the same pseudonyms in later runs.")

    # read key from environment variable
    else:
        key = os.environ.get(key_env_variable, '').strip()
        if not key:
            raise SystemExit(f"No pseudonymization key given. Use --key-file PATH (created if it does not exist) "
                             f"or set the environment variable {key_env_variable}.")

    if len(key) < 16:
        raise SystemExit("Pseudonymization key is too short (at least 16 characters required).")

    return key.encode()


""" PSEUDONYMS """

def pseudonym(value: str, key: bytes) -> str:
    """
    Compute the pseudonym of an identifier value as keyed hash (HMAC-SHA256).

    Inputs:
        - value: str = original identifier value
        - key: bytes = secret key

    Outputs:
        - pseudonym: str = hexadecimal pseudonym
    """

    return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()

def study_pseudonym(value: str, study_uid: str, key: bytes) -> str:
    """
    Compute the study-level pseudonym of an identifier value: different for each study of the same identifier
    value, so that studies of the same patient cannot be linked without the key.

    Inputs:
        - value: str = original identifier value
        - study_uid: str = original StudyInstanceUID
        - key: bytes = secret key

    Outputs:
        - pseudonym: str = hexadecimal pseudonym
    """

    return hmac.new(key, f'study:{value}|{study_uid}'.encode('utf-8'), hashlib.sha256).hexdigest()

def compute_pseudonyms(original_id: str, study_uid: str, key: bytes, linkage: str = 'patient') -> tuple[str, str]:
    """
    Compute the pseudonym of an identifier value according to the linkage level, and its patient-level pseudonym.

    Inputs:
        - original_id: str = original identifier value
        - study_uid: str = original StudyInstanceUID (used for study-level linkage)
        - key: bytes = secret key
        - linkage: str = 'patient' or 'study' (default = 'patient')

    Outputs:
        - pseudo_id: str = pseudonym (patient-level, or study-level for study linkage)
        - patient_pseudo_id: str = patient-level pseudonym (only stored in the linking table)
    """

    if linkage not in LINKAGES:
        raise SystemExit(f"Linkage '{linkage}' not supported. (Use one of: {', '.join(LINKAGES)})")

    patient_pseudo_id = pseudonym(original_id, key)
    pseudo_id = study_pseudonym(original_id, study_uid, key) if linkage == 'study' else patient_pseudo_id
    return pseudo_id, patient_pseudo_id

def pseudo_uid(uid: str, key: bytes, scope: str = '') -> str:
    """
    Compute the pseudonymized UID of an original UID with a keyed hash, so that the same original UID is
    always replaced by the same pseudonymized UID (across files and runs using the same key and scope).

    Inputs:
        - uid: str = original UID
        - key: bytes = secret key
        - scope: str = scope of the mapping (default = '' => global; original StudyInstanceUID for study-level
                       linkage, so that UIDs shared between studies are replaced differently in each study)

    Outputs:
        - pseudo_uid: str = pseudonymized UID (UUID-derived '2.25.<128-bit integer>' form, max 44 characters)
    """

    message = b'uid:' + (scope.encode() + b'|' if scope else b'') + uid.encode()
    digest = hmac.new(key, message, hashlib.sha256).hexdigest()
    return '2.25.' + str(int(digest[:32], 16))


""" IDENTIFIER """

def get_identifier_value(dicom_data: pydicom.dataset.FileDataset, identifier: str, identifiers: dict = IDENTIFIERS) -> tuple[str, Tag]:
    """
    Get the value of the chosen identifier from the first candidate tag that holds a non-empty value.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object (in which the identifier is present)
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

def apply_pseudonym(dicom_data: pydicom.dataset.FileDataset, identifier: str, key: bytes, deidentification_method: str = '', linkage: str = 'patient', identifiers: dict = IDENTIFIERS) -> tuple[pydicom.dataset.FileDataset, dict]:
    """
    Pseudonymize the chosen identifier with a keyed hash, blank it in the DICOM, write the pseudonym in
    PatientID and PatientName, flag the file as de-identified, and return the mapping.

    Inputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object (in which the identifier is present)
        - identifier: str = name of the identifier (key of identifiers)
        - key: bytes = secret key
        - deidentification_method: str = description stored in DeidentificationMethod (default = '')
        - linkage: str = 'patient' (one pseudonym per identifier value) or 'study' (one pseudonym per study,
                         computed from the identifier value and the original StudyInstanceUID) (default = 'patient')
        - identifiers: dict = candidate tags for each identifier (default = IDENTIFIERS)

    Outputs:
        - dicom_data: pydicom.dataset.FileDataset = dicom file object
        - identifier_link: dict = link between identifier, pseudonym written in the DICOM and patient-level
                                  pseudonym (only stored in the linking table) (None if identifier not found)
    """

    original_id, tag = get_identifier_value(dicom_data, identifier, identifiers)

    if original_id is None:
        return dicom_data, None

    # pseudonym written in the DICOM according to the linkage level, and patient-level pseudonym
    pseudo_id, patient_pseudo_id = compute_pseudonyms(original_id, str(dicom_data.get('StudyInstanceUID', '')), key, linkage)

    # remove PHI from the DICOM and write the pseudonym, so images can be linked via the linking table
    dicom_data[tag].value = ''
    dicom_data.PatientID = pseudo_id
    dicom_data.PatientName = pseudo_id

    # flag the file as de-identified (DICOM PS3.15 Annex E)
    dicom_data.PatientIdentityRemoved = 'YES'
    dicom_data.DeidentificationMethod = deidentification_method

    identifier_link = {
        f'Original {identifier}': [original_id],
        f'Pseudonym {identifier}': [pseudo_id],
        f'Patient pseudonym {identifier}': [patient_pseudo_id],
        'Linkage': [linkage]
    }

    return dicom_data, identifier_link


""" UIDS """

def remap_uids(dataset: pydicom.dataset.Dataset, key: bytes, scope: str = '', uids_not_remapped: set = UIDS_NOT_REMAPPED) -> None:
    """
    Replace all instance UIDs of a dataset (including those nested in sequences, e.g. references to other
    instances, series or frames of reference) by their pseudonymized UIDs. Well-known UIDs (SOP classes,
    transfer syntaxes, ...) are kept.

    Inputs:
        - dataset: pydicom.dataset.Dataset = dataset to modify in place
        - key: bytes = secret key
        - scope: str = scope of the UID mapping (default = '' => global, see pseudo_uid)
        - uids_not_remapped: set = keywords of UID attributes to keep (default = UIDS_NOT_REMAPPED)
    """

    def remap(uid):
        uid = str(uid).strip(' \x00')
        if not uid or uid in UID_dictionary:
            return uid
        return pseudo_uid(uid, key, scope)

    for elem in dataset.iterall():
        if elem.VR != 'UI' or elem.keyword in uids_not_remapped or elem.value in (None, ''):
            continue
        if elem.VM > 1:
            elem.value = [remap(uid) for uid in elem.value]
        else:
            elem.value = remap(elem.value)

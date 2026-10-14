"""
Configuration loaded from the JSON files in config/ (fields, groups, identifiers, profiles) and general settings.
"""

""" IMPORTS """

# Pre-installed packages
import os
import json
from importlib.metadata import version, PackageNotFoundError

# Pydicom
from pydicom.tag import Tag


""" CONFIGURATION FILES """

# Folder containing the JSON configuration files (tags, groups, identifiers, profiles)
CONFIG_FOLDER = os.path.join(os.path.dirname(__file__), 'config')

# User-defined profile (profile 0), editable with modify_profile
USER_PROFILE_FILEPATH = os.path.join(CONFIG_FOLDER, 'profile.json')

# Environment variable that can hold the secret pseudonymization key (alternative to --key-file)
KEY_ENV_VARIABLE = 'DICOM_PSEUDO_KEY'

# Linkage levels of the pseudonyms:
#   - patient: one pseudonym per patient (identifier), studies of the same patient can be linked
#   - study: one pseudonym per study, studies of the same patient cannot be linked without the key
LINKAGES = ('patient', 'study')

# Version of this tool, recorded in the DeidentificationMethod of the pseudonymized files
try:
    TOOL_VERSION = version('dicom_pseudo')
except PackageNotFoundError:
    TOOL_VERSION = 'unknown'


""" FUNCTIONS """

def _load_json(filepath: str):
    """
    Load a JSON configuration file.

    Inputs:
        - filepath: str = path to JSON file

    Outputs:
        - data = content of the JSON file
    """

    try:
        with open(filepath, 'r') as file:
            return json.load(file)
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid configuration file '{filepath}': {error}")

def _to_int(value, name: str, filepath: str) -> int:
    """
    Convert a tag or group given as int, hex string ('0x00101010') or keyword ('PatientAge') to an int.

    Inputs:
        - value: int | str = tag or group value
        - name: str = name of the entry (for error messages)
        - filepath: str = path to the configuration file (for error messages)

    Outputs:
        - value: int = tag or group as int
    """

    try:
        if isinstance(value, str) and value.lower().startswith('0x') and len(value) <= 6:
            return int(value, 16)       # group, e.g. '0x0028'
        return int(Tag(value))
    except Exception:
        raise SystemExit(f"Invalid tag '{value}' for '{name}' in configuration file '{filepath}'.")

def load_tags(filepath: str) -> dict:
    """
    Load a dictionary of DICOM keywords (keys) and tags (values) from a JSON file. The entries may be grouped
    by category (nested dictionaries), which are flattened.

    Inputs:
        - filepath: str = path to JSON file

    Outputs:
        - tags: dict = dictionary of DICOM keywords (keys) and their tags as int (values)
    """

    def flatten(entries: dict) -> dict:
        tags = {}
        for name, value in entries.items():
            if isinstance(value, dict):
                tags.update(flatten(value))
            else:
                tags[name] = _to_int(value, name, filepath)
        return tags

    return flatten(_load_json(filepath))

def _config(filename: str) -> str:
    """
    Get the path to a configuration file.
    """

    return os.path.join(CONFIG_FOLDER, filename)


""" DEFINITION OF TAGS AND TAG GROUPS (from configuration files) """

# DICOM tags for the information to be kept in all cases
FIELDS_TO_KEEP = load_tags(_config('fields_to_keep.json'))

# DICOM tag groups for the information to be kept in all cases
GROUPS_TO_KEEP = set(load_tags(_config('groups_to_keep.json')).values())

# File meta information elements to keep (all others, e.g. Source/Sending AE Titles, are removed)
FILE_META_TO_KEEP = set(load_tags(_config('file_meta_to_keep.json')).values())

# Possible identifiers for one DICOM file (candidate tags, tried in order until a non-empty value is found)
IDENTIFIERS = {identifier: [_to_int(tag, identifier, _config('identifiers.json')) for tag in tags]
               for identifier, tags in _load_json(_config('identifiers.json')).items()}

# UID attributes that refer to a class, syntax or coding scheme (not to an instance), never remapped
UIDS_NOT_REMAPPED = set(_load_json(_config('uids_not_remapped.json')))

# Repeating groups (overlays 60xx, curves 50xx) removed entirely when not kept, as they can hold burned-in annotations
REPEATING_GROUPS_TO_REMOVE = tuple(range(int(first, 16), int(last, 16) + 1)
                                   for first, last in _load_json(_config('repeating_groups_to_remove.json')).values())

# Predefined profiles (profile 0 is the user-defined profile)
PROFILES = _load_json(_config('profiles.json'))


""" PROFILES """

def profile_descriptions() -> str:
    """
    Get a short description of all available profiles (for help and error messages).
    """

    descriptions = ['0: user-defined (profile.json)']
    descriptions += [f"{number}: {profile['description']}" for number, profile in PROFILES.items()]
    return ', '.join(descriptions)

def select_profile(profile: int, fields_to_keep: dict = FIELDS_TO_KEEP, groups_to_keep: set = GROUPS_TO_KEEP) -> tuple[dict, set]:
    """
    Select the field to keep based on the profile.

    Inputs:
        - profile: int = number corresponding to profile to be selected (0 = user-defined profile.json, others from profiles.json)
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep (default = FIELDS_TO_KEEP)
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep (default = GROUPS_TO_KEEP)

    Ouptuts:
        - fields_to_keep: dict = dictionary of DICOM keywords (keys) and their tags (values) of the fields to keep
        - groups_to_keep: set = set of DICOM keyword groups of the fields to keep
    """

    # select profile from profile.json file
    if profile == 0:
        extra_fields_to_keep = load_tags(USER_PROFILE_FILEPATH)

    # select predefined profile
    elif str(profile) in PROFILES:
        filepath = _config('profiles.json')
        extra_fields_to_keep = {name: _to_int(tag, name, filepath) for name, tag in PROFILES[str(profile)]['fields'].items()}

    # other profile parameter inputs are incorrect
    else:
        raise SystemExit(f"Profile '{profile}' not supported. ({profile_descriptions()})")

    # combine fields to keep with extra fields corresponding to profile (copies, the defaults must not be mutated)
    fields_to_keep = {**fields_to_keep, **extra_fields_to_keep}
    groups_to_keep = set(groups_to_keep)

    return fields_to_keep, groups_to_keep

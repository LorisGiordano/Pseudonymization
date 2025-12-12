# Pseudonymization

## Dependencies

### Required
  - python == 3.11.11
    - argparse
    - os
    - hashlib
    - json
  - pandas == 2.1.4
  - pydicom == 3.0.1

`pip install pandas==2.1.4`

`pip install pydicom==3.0.1`


### Optional
  - [tqdm]
  - [presidio_image_redactor == 0.0.53]
     - dependencies:
           azure-ai-formrecognizer
           matplotlib
           opencv-python
           pillow
           presidio-analyzer
           pypng
           pytesseract
           python-gdcm
     - Presidio image redactor uses the presidio-analyzer which requires a spaCy language model:
    python -m spacy download en_core_web_lg

`pip install presidio_image_redactor`\
`python -m spacy download en_core_web_lg`


### Conda install


`conda create -n pseudo python==3.11 pandas==2.1.4`\
`conda activate pseudo`\
`pip install pydicom==3.0.1 presidio_image_redactor`\
`python -m spacy download en_core_web_lg`


## [Pseudonyminzation](https://github.com/LorisGiordano/Pseudonymization/blob/main/pseudonymization.py)

`python pseudonymization.py INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER`

- INPUT_ROOT = Input root
- [OUTPUT_ROOT] = Output root => default = INPUT_ROOT_pseudonymized
- [PROFILE] = Pseudonymization profile  =>  default = 1
    - profile 0: user-defined -> profile.json
    - profile 1: pseudonymization (age, sex, height, weight)
    - profile 2: pseudonymization (age, sex, height, weight) + study time
    - profile 3: anonymization for 4D data
- [IDENTIFIER] = Pseodnymization identifier => default = AgfaID
    - PatientID
    - StudyID
    - AgfaID (AccessionNumber / 7fdd,1013)

### Field retention changes

| Field(s) | Stored before fix? | Previous behavior | Current behavior |
| --- | --- | --- | --- |
| `PatientID`/`StudyID`/`AgfaID` (selected identifier) | No | Identifier was hashed but then removed from the DICOM because it was not part of the keep list; the value only lived in the Excel link table. | Identifiers are hashed for the Excel/linking workflow, but the corresponding DICOM fields are now blanked so no identifier—hashed or otherwise—gets stored in the files. |
| `StudyInstanceUID`, `SeriesInstanceUID`, `FrameOfReferenceUID` + file meta UIDs (`MediaStorageSOPClassUID`, `MediaStorageSOPInstanceUID`) | Partially | Study/series/frame UIDs were replaced, but the file meta block could retain stale SOP references, which confused some DICOM readers. | File meta information is regenerated so that the SOP UIDs match the dataset after pseudonymization. |
| All other stripped attributes (everything outside the keep lists) | No (and sometimes invalid) | Attributes were deleted outright or had their values set to `None`, producing structurally invalid datasets for certain VR types. | Attributes are now zeroed/emptied with VR-aware placeholders (empty strings, zeros, or empty sequences), so the DICOM structure stays valid even though the sensitive values are cleared. |


## [Burnt-in text deidentification](https://github.com/LorisGiordano/Pseudonymization/blob/main/presidio.py)

`python presidio.py INPUT_ROOT -b BOX_TYPE`

- INPUT_ROOT = Input root
- [BOX_TYPE] -> default = background
    - background
    - contrast


## [Extraction](https://github.com/LorisGiordano/Pseudonymization/blob/main/extraction.py)

`python extraction.py INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -t TIMESTAMP`

- INPUT_ROOT = Input root
- [OUTPUT_ROOT] = Output root => default = INPUT_ROOT_extracted
- [PROFILE] = Pseudonymization profile  =>  default = 1
    - profile 0: user-defined -> profile.json
    - profile 1: pseudonymization (age, sex, height, weight)
    - profile 2: pseudonymization (age, sex, height, weight) + study time
    - profile 3: anonymization for 4D data
- [IDENTIFIER] = Pseudonymization identifier => default = AgfaID
    - PatientID
    - StudyID
    - AgfaID (AccessionNumber / 7fdd,1013)
- [TIMESTAMP] = Timestamp keyword for 4D data => default = None (auto-detection)
    - TimeStamp (0019,1024)
    - AcquisitionTime
    - ContentTime
 
## [Check output](https://github.com/LorisGiordano/Pseudonymization/blob/main/compare_nifti.py)

`python compare_nifti.py FILE_PATH1 FILE_PATH2 -t TOLERANCE`

- FILE_PATH1 = original DICOM file transformed to NifTi
- FILE_PATH2 = pseudonymized DICOM file transformed to NifTi
- [TOLERANCE] = numerical tolerance when comparing pixel/voxel values

# Pseudonymization

Utilities for pseudonymizing DICOM datasets

## Install

### Python venv

``` bash
python -m venv pseudo
source pseudo/bin/activate
pip install --upgrade pip
pip install -e .
```

### Conda

```bash
conda create -n pseudo python==3.11
conda activate pseudo
pip install --upgrade pip
pip install .
```

### Optional

```bash
pip install presidio_image_redactor==0.0.53
python -m spacy download en_core_web_lg
```

- dependencies:
    - azure-ai-formrecognizer
    - matplotlib
    - opencv-python
    - pillow
    - presidio-analyzer
    - pypng
    - pytesseract
    - python-gdcm
- Presidio image redactor uses the presidio-analyzer which requires a spaCy language model


## Pseudonyminzation

```bash
pseudonymize INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER
```

- INPUT_ROOT = Input root
- [OUTPUT_ROOT] = Output root
    - *default = INPUT_ROOT_pseudonymized*
- [PROFILE] = Pseudonymization profile
    - profile 0: user-defined -> profile.json
    - profile 1: pseudonymization (age, sex, height, weight)
    - profile 2: pseudonymization (age, sex, height, weight) + study time
    - profile 3: anonymization for 4D data
    - *default = 1*
- [IDENTIFIER] = Pseodnymization identifier
    - PatientID
    - StudyID
    - AgfaID (AccessionNumber / 7fdd,1013)
    - *default = AgfaID*

### Profile

```bash
modify_profile
```

Opens an editor in order to modify the custom profile for pseudonymization.

### Field retention




## Burnt-in text deidentification

```bash
python presidio.py INPUT_ROOT -b BOX_TYPE
```

- INPUT_ROOT = Input root
- [BOX_TYPE]
    - background
    - contrast
    - *defailt = background*


## Extraction

```bash
exrtact INPUT_ROOT -o OUTPUT_ROOT -p PROFILE -i IDENTIFIER -t TIMESTAMP
```

- INPUT_ROOT = Input root
- [OUTPUT_ROOT] = Output root
    - *default = INPUT_ROOT_extracted*
- [PROFILE] = Pseudonymization profile
    - profile 0: user-defined -> profile.json
    - profile 1: pseudonymization (age, sex, height, weight)
    - profile 2: pseudonymization (age, sex, height, weight) + study time
    - profile 3: anonymization for 4D data
    - *default = 1*
- [IDENTIFIER] = Pseudonymization identifier
    - PatientID
    - StudyID
    - AgfaID (AccessionNumber / 7fdd,1013)
    - *default = AgfaID*
- [TIMESTAMP] = Timestamp keyword for 4D data
    - TimeStamp (0019,1024)
    - AcquisitionTime
    - ContentTime
    - *default = None => auto-detection*
 
## Check output

```bash
compare FILE_PATH1 FILE_PATH2 -t TOLERANCE
```

- FILE_PATH1 = original DICOM file transformed to NifTi
- FILE_PATH2 = pseudonymized DICOM file transformed to NifTi
- [TOLERANCE] = numerical tolerance when comparing pixel/voxel values
    - *default = 1e-5*

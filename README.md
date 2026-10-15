# dicom_pseudo

Pseudonymization of DICOM datasets for research. The package provides two pipelines, which you can use from the
command line or as a Python API:

- **Pseudonymization** (`pseudonymize`): writes pseudonymized DICOM files. It keeps the image and the fields of the
  selected profile, replaces the patient identifier and all UIDs with keyed pseudonyms, and removes or empties
  everything else.
- **Extraction** (`extract`): writes pseudonymized NIfTI images (2D, 3D or 4D), together with the profile's metadata
  as JSON.

Both use the same secret key, so they give the same pseudonyms and the same output folder structure. Both write a
**linking table** between original and pseudonymized identifiers, which must be kept separately from the data. Two
helper commands complete the toolkit: `redact` removes text burned into the pixel data, and `compare` compares two
NIfTI files.

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Concepts](#concepts)
- [Pseudonymization: `pseudonymize`](#pseudonymization-pseudonymize)
- [Extraction: `extract`](#extraction-extract)
- [Arguments](#arguments)
- [Profiles](#profiles)
- [Python API](#python-api)
- [Example scripts](#example-scripts)
- [Other commands](#other-commands)
- [Limitations and good practice](#limitations-and-good-practice)

## Install

```bash
conda create -n pseudo python=3.12.10
conda activate pseudo
pip install --upgrade pip
pip install .
```

Requires Python 3.10 or newer.

```bash
python -m venv pseudo
source pseudo/bin/activate
pip install --upgrade pip
pip install .
```

This installs the commands `pseudonymize`, `extract`, `redact`, `compare` and `modify_profile`. 
NIfTI conversion uses `dicom2nifti`, `nibabel` and `numpy`, which are installed automatically.

Redacting burned-in text is optional, because Microsoft Presidio is a large dependency:

```bash
pip install '.[presidio]'
python -m spacy download en_core_web_lg
brew install tesseract   # Tesseract OCR engine; on Linux: apt install tesseract-ocr
```

## Quick start

```bash
# pseudonymized DICOM files
pseudonymize /data/study -o /release/dicom -k /secrets/project.key -l /secrets/linking_table.xlsx

# pseudonymized NIfTI images and metadata (same key: same pseudonyms and folders)
extract /data/study -o /release/nifti -k /secrets/project.key -l /secrets/linking_table_nifti.xlsx
```

The key file is created at the first run. Keep it, and the linking tables, in a protected location outside the data you share. 
The same key gives the same pseudonyms in later runs.

## Concepts

### Secret key and pseudonyms

Pseudonyms are keyed hashes (HMAC-SHA256) of the original identifier. 
Without the key, they can't be recomputed, and low-entropy identifiers such as numeric patient IDs can't be recovered by trying every possible value.

- `--key-file PATH` reads the key from a file, or creates a new random key file (readable only by its owner) if it
  doesn't exist yet. Alternatively, set the environment variable `DICOM_PSEUDO_KEY`.
- **The key defines the scope of linkage.** Reuse the same key for all exports of a project, so a patient keeps the same pseudonym. 
  Use a new key for each separate project or data release, so the releases can't be joined with each other.
- The key file and the linking table are refused if they are inside the output folder.

### Linkage: patient or study level

`--linkage patient` (default) gives one pseudonym per patient (per identifier value): all studies of a patient share it, which allows longitudinal analyses.

`--linkage study` gives one pseudonym per study, computed from the identifier and the original StudyInstanceUID. 
All UIDs are also mapped per study, so a UID shared between two studies (e.g. a frame of reference) is replaced differently in each. 
Studies of the same patient then can't be linked in the released data. 
The linking table still lists the patient-level pseudonym of each study, so the key holder can re-link them.

### What happens to a DICOM file

| Element | Result |
|---|---|
| Identifier (`--identifier`) | Pseudonymized; the pseudonym is written to PatientID and PatientName |
| De-identification flags | `PatientIdentityRemoved = YES`; `DeidentificationMethod` records the tool version, profile, identifier and linkage |
| UIDs (study, series, instance, frame of reference, references between instances) | Replaced by keyed UIDs (`2.25.<number>`), the same on every run with the same key, so references stay valid. Standard UIDs (SOP class, transfer syntax) are kept |
| Fields kept in all profiles | Kept unchanged ([list](#fields-kept-in-all-profiles)) |
| Fields of the selected profile | Kept unchanged ([profiles](#profiles)) |
| All other fields | Emptied (zero-length value, so the file structure stays valid); sequences keep only their UIDs |
| Private (vendor) tags | Removed, unless a profile keeps them explicitly |
| Overlays and curves (groups 60xx, 50xx) | Removed, as they can contain burned-in annotations |
| File meta information | Reduced to the elements a valid file needs (no station / AE titles) |
| Pixel data | Unchanged (to redact burned-in text, see [`redact`](#redact-burned-in-text)) |

### Input files

The input can be a folder, searched recursively, or a single DICOM file. 
DICOMDIR index files and non-DICOM files (README, reports, …) are ignored and never copied. 
Damaged files, and files without the chosen identifier, are skipped and listed at the end of the run.

### Output structure

Output folders and file names are rebuilt from pseudonymized values only, because input paths often contain names, IDs or dates:

```
OUTPUT/<pseudonym, first 16 characters>/<pseudonymized StudyInstanceUID>/<pseudonymized SeriesInstanceUID>/
```

The input and output folders must not be inside each other. 
A missing output folder is created; the default is `INPUT_pseudonymized` (`pseudonymize`) or `INPUT_extracted` (`extract`), next to the input.

### Linking table

`--link-table PATH` (`.xlsx` or `.csv`, required) has one row per DICOM series (and input/output folder). 
It contains the original identifiers, so treat it like the key. 
An existing table is updated: re-running replaces the rows of the same series, and new series are added.

| Column | Content |
|---|---|
| `Original <identifier>` | Original identifier value |
| `Pseudonym <identifier>` | Pseudonym written in the data (patient or study level) |
| `Patient pseudonym <identifier>` | Patient-level pseudonym (allows re-linking study-level data) |
| `Linkage` | `patient` or `study` |
| `Original / Pseudonymized StudyInstanceUID`, `… SeriesInstanceUID` | Original and pseudonymized UIDs |
| `Modality`, `SeriesNumber`, `SeriesDescription`, `BurnedInAnnotation` | From the original data |
| `Input folder`, `Output folder` | Relative input folder(s) and pseudonymized output folder |
| `Number of files` | Number of DICOM files of the series |
| `NIfTI`, `Number of NIfTI files`, `Time points`, `Time keyword` | `extract` only: 2D/3D/4D, files written, 4D time points and the field used to find them |

## Pseudonymization: `pseudonymize`

```bash
pseudonymize INPUT [-o OUTPUT] [-p PROFILE] [-i IDENTIFIER] [--linkage {patient,study}] -l LINK_TABLE [-k KEY_FILE]
```

Writes one pseudonymized DICOM file per input file: `OUTPUT/<pseudonym>/<study UID>/<series UID>/<SOPInstanceUID>.dcm`. 
If the same instance (SOPInstanceUID) appears twice in the input, it is written once and the duplicate is reported.

## Extraction: `extract`

```bash
extract INPUT [-o OUTPUT] [-p PROFILE] [-i IDENTIFIER] [--linkage {patient,study}] -l LINK_TABLE [-k KEY_FILE] [-t TIMESTAMP]
```

Groups the input files by series (a folder may contain several series) and writes each series to the same pseudonymized folder as `pseudonymize` would. 
It reads the original DICOM files, so all information is available for the conversion, and only pseudonymized values and the profile's metadata are written:

| Series | Files written |
|---|---|
| 3D volume | `image.nii.gz` (conversion with dicom2nifti) |
| 4D, with profile 3 | `0.nii.gz`, `1.nii.gz`, … (one volume per time point) + `timestamps.json` (field used, time label of each volume) |
| 2D image(s) that don't form a volume (CR, DX, MG, localizers) | `image.nii.gz`, or `image_0.nii.gz`, `image_1.nii.gz`, … for several images (InstanceNumber order). Same pixel scaling, orientation and header as dicom2nifti; projection images use `PixelSpacing` (or `ImagerPixelSpacing`) as voxel size |
| All series | `metadata.json`: the profile's fields (see [Profiles](#profiles)) |

`OUTPUT/metadata.xlsx` gives an overview with one row per series: pseudonym, output folder, modality, time points and the profile's fields. 
It contains no original identifiers. 
Series that dicom2nifti can't convert (e.g. inconsistent slice spacing, multi-frame 2D) are listed at the end of the run:

**4D time points.** With profile 3, the time points of a series are detected automatically. 
The first field that splits the series into more than one time point, each covering the same slice positions, is used:

1. `TemporalPositionIdentifier`
2. `NumberOfTemporalPositions`: with the files sorted by InstanceNumber, the k-th image at each slice position belongs to time point k
3. `ContentTime`, `AcquisitionTime`, `TimeStamp` (GE private `0019,1024`)

Series without a temporal dimension are written as 3D. `-t KEYWORD` forces one of these fields; series where it doesn't work are reported.

## Arguments

| Argument | `pseudonymize` | `extract` | Values | Default |
|---|---|---|---|---|
| `INPUT` | ✓ | ✓ | Folder (searched recursively) or single DICOM file | required |
| `-o, --output` | ✓ | ✓ | Output folder, not inside the input (and vice versa) | `INPUT_pseudonymized` / `INPUT_extracted` |
| `-p, --profile` | ✓ | ✓ | `0`–`4`, see [Profiles](#profiles) | `1` |
| `-i, --identifier` | ✓ | ✓ | `PatientID`, `StudyID`, `AccessionNumber`, `AgfaID` | `PatientID` |
| `--linkage` | ✓ | ✓ | `patient`, `study` | `patient` |
| `-l, --link-table` | ✓ | ✓ | `.xlsx` or `.csv` file, not inside the output | required |
| `-k, --key-file` | ✓ | ✓ | Key file, created if missing, not inside the output | environment variable `DICOM_PSEUDO_KEY` |
| `-t, --timestamp` | | ✓ | `TemporalPositionIdentifier`, `NumberOfTemporalPositions`, `ContentTime`, `AcquisitionTime`, `TimeStamp` | automatic detection (profile 3) |

**Identifiers.** The value is read from the first of these tags that holds a non-empty value:

| Identifier | DICOM tags | Note |
|---|---|---|
| `PatientID` | PatientID (0010,0020) | Recommended: one pseudonym per patient |
| `StudyID` | StudyID (0020,0010) | one pseudonym per study |
| `AccessionNumber` / `AgfaID` | AccessionNumber (0008,0050), then private tag (7fdd,1013) | one pseudonym per examination |

Whatever the identifier, the pseudonym is written to PatientID and PatientName. 
The identifiers are configured in `src/dicom_pseudo/core/config/identifiers.json`.

## Profiles

A profile chooses which fields are kept **on top of** the fields kept in all profiles. 
The profiles are defined in `src/dicom_pseudo/core/config/profiles.json`; tags can be given as hex strings (`"0x00101010"`) or keywords (`"PatientAge"`), optionally grouped by category.

| Profile | Use | Fields kept on top of the common fields |
|---|---|---|
| `0` | User-defined | The fields of `profile.json` |
| `1` (default) | Demographics | PatientAge, PatientSex, PatientWeight, PatientSize, PatientSizeCodeSequence, PatientBodyMassIndex |
| `2` | Demographics + date | Profile 1 + StudyDate, SeriesDate |
| `3` | 4D data | ContentTime, AcquisitionTime, TimeStamp (GE private 0019,1024), TemporalPositionIdentifier, NumberOfTemporalPositions. No demographics |
| `4` | Machine | Equipment, acquisition and reconstruction parameters, general to the machine and not to the installation or site (below). No demographics |

**Profile 4 (machine).** Only standard DICOM tags; private tags are still removed.

| Category | Fields |
|---|---|
| Equipment | ManufacturerModelName, SoftwareVersions, SpatialResolution |
| MR | SequenceName, ImagedNucleus, NumberOfPhaseEncodingSteps, PercentSampling, PercentPhaseFieldOfView, ReceiveCoilName, TransmitCoilName, VariableFlipAngleFlag, AngioFlag, ParallelAcquisitionTechnique, ParallelReductionFactorInPlane, DiffusionBValue, DiffusionGradientOrientation |
| CT | FilterType, GeneratorPower, FocalSpots, RevolutionTime, SingleCollimationWidth, TotalCollimationWidth, TableSpeed, TableFeedPerRotation, SpiralPitchFactor, ExposureModulationType, CTDIvol |
| X-ray (CR/DX/MG) | DetectorType, DetectorConfiguration, AnodeTargetMaterial, FilterMaterial, Grid, DistanceSourceToPatient |
| PET/NM | ReconstructionMethod, AttenuationCorrectionMethod, ScatterCorrectionMethod, RandomsCorrectionMethod, CountsSource, CollimatorType |

### Fields kept in all profiles

Configured in `src/dicom_pseudo/core/config/fields_to_keep.json` and `groups_to_keep.json`:

| Category | Fields |
|---|---|
| File integrity | SpecificCharacterSet, ImageType, Manufacturer, SOPClassUID, SOPInstanceUID |
| UIDs (pseudonymized) | StudyInstanceUID, SeriesInstanceUID, FrameOfReferenceUID |
| Image | Modality, SeriesNumber, AcquisitionNumber, InstanceNumber, PatientPosition, ImagePositionPatient, ImageOrientationPatient, SliceLocation, SliceThickness |
| MR acquisition | ScanningSequence, SequenceVariant, ScanOptions, MRAcquisitionType, RepetitionTime, EchoTime, InversionTime, NumberOfAverages, ImagingFrequency, EchoNumbers, MagneticFieldStrength, SpacingBetweenSlices, EchoTrainLength, PixelBandwidth, AcquisitionMatrix, InPlanePhaseEncodingDirection, FlipAngle |
| CT / X-ray acquisition | KVP, DataCollectionDiameter, ReconstructionDiameter, DistanceSourceToDetector, GantryDetectorTilt, ExposureTime, XRayTubeCurrent, Exposure, ImagerPixelSpacing, ConvolutionKernel, ViewPosition |
| PET | Units, DecayCorrection |
| Image pixel description, pixel data | Groups 0028 and 7FE0 (rows, columns, spacing, rescale, window, pixel data) |

### User-defined profile (profile 0)

```bash
modify_profile          # opens profile.json in the default editor
modify_profile --path   # prints the path of profile.json
```

`profile.json` is a dictionary of DICOM keywords and tags, e.g. `{"PatientAge": "0x00101010", "StudyDate": "StudyDate"}`.
Tags can be looked up in the [DICOM standard](https://dicom.nema.org/medical/dicom/current/output/chtml/part06/chapter_6.html).
A new predefined profile is added by adding an entry to `profiles.json`: `"5": {"description": "...", "fields": {...}}`.

## Python API

The pipelines can be called from Python with the same arguments as the commands. 
Configuration errors (unknown profile or identifier, key or linking table inside the output, …) raise `SystemExit` with a message. 
Files that can't be processed are reported and skipped; they don't raise.

```python
from dicom_pseudo.pseudonymization import pseudonymization
from dicom_pseudo.extraction import extraction

pseudonymization(
    input_root='/data/study',                 # folder or single DICOM file
    output_root='/release/dicom',             # outside the input
    profile=1,                                # 0-4
    identifier='PatientID',                   # PatientID, StudyID, AccessionNumber, AgfaID
    key_file='/secrets/project.key',          # None: environment variable DICOM_PSEUDO_KEY
    link_table='/secrets/linking_table.xlsx', # .xlsx or .csv, outside the output
    linkage='patient',                        # 'patient' or 'study'
    progress_bar=True,
)

extraction(
    input_root='/data/study',
    output_root='/release/nifti',
    profile=3,                                # profile 3: 4D reconstruction
    identifier='PatientID',
    time_stamp=None,                          # None: automatic, or e.g. 'NumberOfTemporalPositions'
    key_file='/secrets/project.key',
    link_table='/secrets/linking_table_nifti.xlsx',
    linkage='patient',
)
```

Lower-level building blocks, e.g. for your own pipeline:

| Module | Main functions |
|---|---|
| `dicom_pseudo.core.settings` | `select_profile(profile)`: fields and groups to keep; `FIELDS_TO_KEEP`, `IDENTIFIERS`, `LINKAGES` |
| `dicom_pseudo.core.pseudonym` | `load_key(key_file)`, `pseudonym(value, key)`, `pseudo_uid(uid, key)` |
| `dicom_pseudo.core.identity` | `identify(dataset, identifier, key, linkage)` returns a `SeriesIdentity` (original/pseudonymized IDs, UIDs, output folder) |
| `dicom_pseudo.core.files` | `find_dicom_files(folder)`, `group_by_series(files)`, `save_dicom(dataset, path)` |
| `dicom_pseudo.pseudonymization.pipeline` | `pseudonymize_dicom(...)`: one file |
| `dicom_pseudo.extraction.nifti` | `write_nifti(files, output_folder, four_d)`, `convert_2d(path, output_file)` |
| `dicom_pseudo.redaction` | `redaction(input_root, output_root, fill='contrast', padding_width=25)` |
| `dicom_pseudo.compare_nifti` | `compare_nifti_files(file1, file2, tolerance=1e-5)` |


## Example scripts

The `examples/` folder contains scripts that can be run on your own data:

| Script | Content |
|---|---|
| `01_command_line.sh DICOM_FOLDER WORK_FOLDER` | Pseudonymized DICOM files, NIfTI images (3D/2D) and 4D NIfTI images from the command line |
| `02_python_api.py DICOM_FOLDER WORK_FOLDER` | The same with the Python API, then a summary of the linking table and the NIfTI overview |
| `03_add_data_later.py BATCH... WORK_FOLDER` | Pseudonymization in several batches with the same key and linking table: the same patient keeps the same pseudonym |

Each script writes `WORK_FOLDER/secrets/` (key, linking tables: keep, don't share) and `WORK_FOLDER/release/` (data to share).

## Other commands

### `redact`: burned-in text [NOT TESTED]

```bash
redact INPUT [-o OUTPUT] [-f {contrast,background}] [--padding PIXELS]
```

Detects text in the pixel data with OCR (Microsoft Presidio and Tesseract) and covers it with boxes. 
Run it on the **pseudonymized** DICOM files: files keep their relative paths, and only the pixel data changes. 
`--fill` sets the box colour (`contrast`, the default, or `background`); 
`--padding` sets the padding around the image for the text detection (default 25 pixels). 
It needs the optional install described in [Install](#install). 
The linking table column `BurnedInAnnotation` and the warning at the end of `pseudonymize` show the series flagged as containing burned-in annotations.

### `compare`: NIfTI files

```bash
compare FILE1 FILE2 [-t TOLERANCE]
```

Compares two NIfTI files, header fields and voxel values (within `TOLERANCE`, default `1e-5`). 
For example, convert a series from the original and from the pseudonymized DICOM files and check that the images are identical.

## Limitations

- **Private tags** are removed. Vendor-specific information they hold is therefore not available in the pseudonymized DICOM files (e.g. Siemens mosaic images can't be unpacked from them); 
- **NIfTI conversion** depends on dicom2nifti for volumes: series it rejects (inconsistent slice spacing, multi-frame 2D, ...) are reported and not written.

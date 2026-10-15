"""
Detection of the time points of a series, for 4D data reconstruction.
"""

""" IMPORTS """

# Pre-installed packages
from collections import Counter, defaultdict

# Pydicom
import pydicom


""" DEFINITION OF TIME STAMPS """

# DICOM keywords that can be used for 4D data reconstruction (tried in this order by the automatic detection):
#   - TemporalPositionIdentifier: temporal position of the image
#   - NumberOfTemporalPositions: number of time points, temporal position derived from the order of the images
#     (k-th image at a spatial position, sorted by InstanceNumber = time point k)
#   - ContentTime, AcquisitionTime, TimeStamp (GE private): time stamps
TIME_STAMP_FIELDS = {
    'TemporalPositionIdentifier':   0x00200100,
    'NumberOfTemporalPositions':    0x00200105,
    'ContentTime':                  0x00080033,
    'AcquisitionTime':              0x00080032,
    'TimeStamp':                    0x00191024
}


""" FUNCTIONS """

def spatial_position(dicom_data: pydicom.dataset.Dataset) -> tuple:
    """
    Get the spatial position of an image (ImagePositionPatient rounded to 0.001 mm, empty if missing).
    """

    return tuple(round(float(value), 3) for value in dicom_data.get('ImagePositionPatient', []) or [])

def time_positions(files: list, time_stamp_keyword: str = None) -> tuple[str, list]:
    """
    Get the time position of each image of a series (for 4D data reconstruction).

    Automatic detection (if no time stamp keyword given), the first keyword giving more than one time point, each
    time point covering the same spatial positions (one volume per time point), is used:
        - TemporalPositionIdentifier
        - NumberOfTemporalPositions (time point = order of the image at its spatial position)
        - ContentTime, AcquisitionTime, TimeStamp

    Inputs:
        - files: list = (path, dataset) of the series, sorted by InstanceNumber
        - time_stamp_keyword: str = DICOM keyword to be used (default = None => automatic detection)

    Outputs:
        - keyword: str = keyword used (None if the series has no temporal dimension)
        - labels: list = time label of each image (None if the series has no temporal dimension)
    """

    if time_stamp_keyword is not None and time_stamp_keyword not in TIME_STAMP_FIELDS:
        raise SystemExit(f"Keyword '{time_stamp_keyword}' cannot be used as a time stamp keyword. (Use one of: {', '.join(TIME_STAMP_FIELDS)})")
    keywords = [time_stamp_keyword] if time_stamp_keyword else list(TIME_STAMP_FIELDS)

    for keyword in keywords:
        tag = TIME_STAMP_FIELDS[keyword]

        # time point derived from the number of temporal positions and the spatial position of the images
        if keyword == 'NumberOfTemporalPositions':
            number = files[0][1].get(tag, None)
            if number is None or int(number.value or 0) < 2:
                continue
            occurrences = Counter()
            labels = []
            for _, dicom_data in files:
                position = spatial_position(dicom_data)
                labels.append(str(occurrences[position]))
                occurrences[position] += 1

        # time point read from the images
        else:
            if any(tag not in dicom_data or dicom_data[tag].value in (None, '') for _, dicom_data in files):
                continue
            labels = [str(dicom_data[tag].value).strip() for _, dicom_data in files]

        # valid if more than one time point, each time point covering the same spatial positions (a 3D volume
        # per time point, not e.g. one slice per time stamp of a 3D stack)
        positions_per_time = defaultdict(list)
        for label, (_, dicom_data) in zip(labels, files):
            positions_per_time[label].append(spatial_position(dicom_data))
        volumes = {tuple(sorted(positions)) for positions in positions_per_time.values()}
        if len(positions_per_time) > 1 and len(volumes) == 1:
            return keyword, labels
        if time_stamp_keyword:
            raise ValueError(f"time stamp keyword '{keyword}' does not give time points covering the same spatial positions")

    return None, None

def sort_labels(labels: set) -> list:
    """
    Sort time labels numerically if possible, otherwise alphabetically.
    """

    try:
        return sorted(labels, key=float)
    except ValueError:
        return sorted(labels)

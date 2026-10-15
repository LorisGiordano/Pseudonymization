""" IMPORTS """
import argparse

# Nibabel
import nibabel as nib

# Numpy
import numpy as np


""" FUNCTIONS """

def _load_nifti(file_path: str) -> tuple[nib.nifti1.Nifti1Image, np.ndarray]:
    """
    Load a NIfTI file and return the image object and data array.

    Inputs:
        - file_path: str = path to input file

    Outputs:
        - image: nib.nifti1.Nifti1Image = nibabel image object
        - image_data: np.ndarray = image data associated with nibabel image
    """

    # load image and its data
    image = nib.load(file_path)
    image_data = image.get_fdata()
    return image, image_data

def _compare_headers(image1: nib.nifti1.Nifti1Image, image2: nib.nifti1.Nifti1Image) -> None:
    """
    Compare the headers of two NIfTI images key by key.

    Inputs:
        - image1: nib.nifti1.Nifti1Image = image for comparison
        - image2: nib.nifti1.Nifti1Image = other image for comparison
    """

    # get headers
    header1 = image1.header
    header2 = image2.header

    # hard check header difference
    full_check = header1 == header2

    # check difference between headers key by key
    header_differences = []
    for key in header1.keys():
        value1 = header1[key]
        value2 = header2[key]
        # NaN values (e.g. unset scl_slope/scl_inter) are equal to each other
        if not np.array_equal(value1, value2, equal_nan=np.asarray(value1).dtype.kind == 'f'):
            header_differences.append((key, value1, value2))

    # print differences in the headers if any
    if header_differences:
        print("\nHeader differences found:")
        for key, value1, value2 in header_differences:
            print(f" - {key}: {value1} != {value2}")
    else:
        print("\nHeaders are identical.")

def _compare_data(image_data1: np.ndarray, image_data2: np.ndarray, tolerance: float = 1e-5) -> None:
    """
    Compare the image data arrays of two NIfTI images.

    Inputs:
        - image_data1: np.ndarray = image data for comparison
        - image_data2: np.ndarray = other image data for comparison
        - tolerance: float = tolerance when considering the difference between 2 pixel/voxel values (default = 1e-5)
    """

    # check sizes
    if image_data1.shape != image_data2.shape:
        print(f"\nData shape mismatch: {image_data1.shape} != {image_data2.shape}")
        return

    # check for differences within a tolerance
    if not np.allclose(image_data1, image_data2, atol=tolerance):
        difference = np.abs(image_data1 - image_data2)
        max_difference = np.max(difference)
        print(f"\nData arrays differ (max difference: {max_difference})")
        return

    print("\nData arrays are identical (within tolerance).")

def compare_nifti_files(file1: str, file2: str, tolerance: float = 1e-5) -> None:
    """
    Main function to compare two NIfTI files. Load the image files to compare and check the differences between the images.

    Inputs:
        - file_path1: str = absolute path to original file for comparison
        - file_path2: str = other absolute path to pseudonymizde file for comparison
        - tolerance: float = tolerance when considering the difference between 2 pixel/voxel values (default = 1e-5)
    """

    print(f"Comparing NIfTI files:\n - File 1: {file1}\n - File 2: {file2}")

    # load images
    image1, image_data1 = _load_nifti(file1)
    image2, image_data2 = _load_nifti(file2)

    # compare headers
    _compare_headers(image1, image2)

    # compare image data
    _compare_data(image_data1, image_data2, tolerance)


""" MAIN """

def main():
    # Parser
    parser = argparse.ArgumentParser(description="Compare two NIfTI files (image data and metadata).")
    parser.add_argument("file_path1", type=str, help="Path to the first NIfTI file (e.g. converted from the original DICOM files).")
    parser.add_argument("file_path2", type=str, help="Path to the second NIfTI file (e.g. converted from the pseudonymized DICOM files).")
    parser.add_argument("--tolerance", "-t", type=float, default=1e-5, help="Tolerance for numerical comparison of image data.")
    args = parser.parse_args()

    # File path 1
    file_path1 = args.file_path1

    # File path 2
    file_path2 = args.file_path2

    # Tolerance
    tolerance = args.tolerance

    # Compare nifti
    compare_nifti_files(file_path1, file_path2, tolerance)


# python compare_nifti.py FILE_PATH1 FILE_PATH2 -t TOLERANCE

if __name__ == "__main__":

    main()

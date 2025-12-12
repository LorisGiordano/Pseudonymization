import pydicom
import sys
import os
from presidio_image_redactor import DicomImageRedactorEngine


def remove_pixel_text(path, selected_box):
    engine = DicomImageRedactorEngine()
    output_dir = "./textPixelRemovalOutput"
    if '.dcm' in path:
        engine.redact_from_file(full_path, output_dir, fill=selected_box)
    else:
        engine.redact_from_directory(full_path, output_dir, fill=selected_box)
    
    print('Text from pixels removal done.')


# FOR RUNNING
if __name__ == '__main__':
    if len(sys.argv) != 3 :
        print("Usage: python myscrip.py directory_name box_type")
        sys.exit(1)
    elif sys.argv[2] != "contrast" and sys.argv[2] != "background":
        print("The box_type parameter has to be 'contrast' or 'background'. Usage: python myscrip.py directory_name box_type")
        sys.exit(1)

    # Get the arguments
    path = sys.argv[1]
    selected_box = sys.argv[2]
    full_path = os.path.abspath(path)
    
    remove_pixel_text(full_path, selected_box)
    

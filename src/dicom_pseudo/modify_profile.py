import os
import argparse
import subprocess
import platform

from dicom_pseudo.core.settings import USER_PROFILE_FILEPATH

def open_with_default_app(path):

    system = platform.system()

    try:
        if system == "Darwin":
            subprocess.run(["open", path])
        elif system == "Windows":
            os.startfile(path)
        else: # Linux
            raise Exception("I do not know Linux")

    except Exception as e:
        try:
            if system == "Darwin":
                subprocess.run(["open", "-e", path])
            elif system == "Windows":
                subprocess.run(["notepad", path])
            else: # Linux
                subprocess.run(["nano", path])
        except:
            print(path)

def main():
    parser = argparse.ArgumentParser(description=f"Open the user-defined profile (profile 0) for editing: {USER_PROFILE_FILEPATH}")
    parser.add_argument('--path', action='store_true', help='Only print the path of the profile file, without opening it.')
    args = parser.parse_args()
    if args.path:
        print(USER_PROFILE_FILEPATH)
    else:
        open_with_default_app(USER_PROFILE_FILEPATH)

if __name__ == "__main__":
    main()
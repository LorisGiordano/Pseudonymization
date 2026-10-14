import os
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
    open_with_default_app(USER_PROFILE_FILEPATH)

if __name__ == "__main__":
    main()
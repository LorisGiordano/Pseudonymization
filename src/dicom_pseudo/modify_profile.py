import os
import subprocess
import platform

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
        if system == "Darwin":
            subprocess.run(["open", "-e", path])
        elif system == "Windows":
            subprocess.run(["notepad", path])
        else: # Linux
            subprocess.run(["nano", path])

def main():
    open_with_default_app(os.path.join(os.path.dirname(__file__), "profile.json"))

if __name__ == "__main__":
    main()
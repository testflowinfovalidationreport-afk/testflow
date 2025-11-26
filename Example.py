"""
Example script for using the `testflow` package.

This script shows how a user can:
1. Import the installed `testflow` package.
2. Provide the path to a .atoms script and an output directory.
3. Call `testflow.run_script(script_path, output_dir)` to execute the script.

To use:
- Make sure `testflow` is installed in this Python environment.
- Update `script_path` and `output_dir` below to match your files.
- Run from the terminal with:  python run_testflow_example.py
"""

import testflow  # make sure `testflow` is installed in this environment


def main():

    # === 1) Set your paths here ===
    script_path = r"C:\.....\test.atoms"
    output_dir  = r"C:\.....\output"


    # === 2) Run the script via the package ===
    testflow.run_script(str(script_path), str(output_dir))



if __name__ == "__main__":
    main()

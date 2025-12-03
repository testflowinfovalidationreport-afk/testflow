"""
Example script for using the `testflow` package in debugging mode.

This script shows how a user can run the script node bu node using debug mode
"""

import testflow  # make sure `testflow` is installed in this environment


def main():

    # === 1) Set your paths here ===
    script_path = r"C:\.....\test.atoms"
    output_dir  = r"C:\.....\output"


    # === 2) Run the script via the package ===
    testflow.run_script(str(script_path), str(output_dir),False,True)



if __name__ == "__main__":
    main()
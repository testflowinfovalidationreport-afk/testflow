TestFlow Python Package

TestFlow is a Python package for executing and validating ATOMS hardware-testing scripts.
It enables engineers to run .atoms test workflows, control instruments, and generate measurement outputs through a simple, programmable interface.

This package is provided under the TestFlow Community License (TCL) — free for internal testing, evaluation, and research, but not permitted for commercial use or integration into competing tools without written permission.

Installation

Clone the repository:

git clone https://github.com/testflowinfovalidationreport-afk/testflow.git
cd testflow


Install locally:

pip install .


Or install in editable/dev mode:

pip install -e .

 Usage Example
import testflow

script_path = r"C:/path/to/script.atoms"
output_path = r"C:/path/to/output_folder/"

testflow.run_script(script_path, output_path)


This will parse the ATOMS script, execute supported commands, interact with connected instruments, and generate output files in the specified directory.

📁 Repository Structure
testflow/
├─ LICENSE
├─ pyproject.toml
└─ src/
    └─ testflow/
        ├─ __init__.py
        └─ runner.py


runner.py
Contains the main execution engine for .atoms scripts.

init.py
Exposes the public API for users.

LICENSE
Custom TestFlow Community License restricting commercial and competitive use.

🔒 License

This project is licensed under the TestFlow Community License (TCL).

✔ Allowed

Internal testing and validation

Research and educational use

Internal modifications for evaluation

✘ Not Allowed

Commercial use

Redistribution of source code

Integrating TestFlow into a commercial product

Building or improving competing tools

Offering TestFlow as a SaaS / cloud service

For commercial licensing, contact:

ali@testflow.ai

See the full terms in the LICENSE file.

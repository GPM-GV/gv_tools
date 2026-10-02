#!/bin/tcsh
# Install and execute with tcsh: tcsh INSTALL.tcsh
set WORKSPACE = "$HOME/Desktop/Work/GV Tools"
set PYTHON = "$HOME/anaconda3/bin/python"
$PYTHON -m pip install "$WORKSPACE/gv_tools/release/gv_tools-0.34.0-py3-none-any.whl[parsivel,netcdf,py_2dvd,sounding]"
if ($status != 0) exit 1
$PYTHON -m gv_tools.cli check
# Example processing command (replace the input path):
# $HOME/anaconda3/bin/gv-tools-2dvd-process /path/to/V23022.drops.txt --output-dir "$WORKSPACE/Output"
# $PYTHON -m jupyter lab "$WORKSPACE/GV_Tools_Ingest_Demonstration.ipynb"

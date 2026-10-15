#!/bin/tcsh
set WORKSPACE = /Users/dwolff/Desktop/Work/GV_Tools
set package_name = gv_tools
set PACKAGE_DIRECTORY = "$WORKSPACE/$package_name"
set PYTHON = "$HOME/anaconda3/bin/python"

$PYTHON -m pip install --upgrade "$PACKAGE_DIRECTORY/dist/gv_tools-0.50.0-py3-none-any.whl[all]"
if ($status != 0) exit 1
$PYTHON -m pip install --force-reinstall --no-deps "$PACKAGE_DIRECTORY/dist/gv_tools-0.50.0-py3-none-any.whl"
if ($status != 0) exit 1
$PYTHON -m gv_tools.cli check --include plot --include radar --include notebook --include sounding

# $PYTHON -m jupyter lab "$PACKAGE_DIRECTORY/notebooks"

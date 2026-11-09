#!/bin/tcsh
set WORKSPACE = "/Users/dwolff/Desktop/Work/GV_Tools"
set PACKAGE_DIR = "$WORKSPACE/gv_tools"
set PYTHON = "$HOME/anaconda3/bin/python"
set WHEEL = "$PACKAGE_DIR/dist/gv_tools-0.65.0-py3-none-any.whl"

if (! -e "$WHEEL") then
    echo "Missing release wheel: $WHEEL"
    exit 1
endif
$PYTHON -m pip install --upgrade "${WHEEL}[all]"
if ($status != 0) exit 1
$PYTHON -c 'import gv_tools; print(gv_tools.__version__)'

# $PYTHON -m gv_tools.cli check --include plot --include radar --include notebook --include sounding

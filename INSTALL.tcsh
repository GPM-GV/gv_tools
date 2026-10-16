#!/bin/tcsh
set PYTHON = "$HOME/anaconda3/bin/python"
set RELEASE_DIR = "$HOME/Downloads"
set WHEEL = "$RELEASE_DIR/gv_tools-0.50.0-py3-none-any.whl"

curl -L "https://github.com/GPM-GV/gv_tools/releases/download/v0.50.0/gv_tools-0.50.0-py3-none-any.whl" -o "$WHEEL"
if ($status != 0) exit 1
$PYTHON -m pip install --upgrade "${WHEEL}[all]"
if ($status != 0) exit 1
$PYTHON -c 'import gv_tools; print(gv_tools.__version__)'

# $PYTHON -m gv_tools.cli check --include plot --include radar --include notebook --include sounding

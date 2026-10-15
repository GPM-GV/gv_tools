Examples
========

Post-processed MRRPro
---------------------

Read an hourly directory into one xarray dataset and save a three-panel
time-height display from ``tcsh``:

.. code-block:: tcsh

   set WORKSPACE = "$HOME/Desktop/Work/GV_Tools"
   set PYTHON = "$HOME/anaconda3/bin/python"
   $PYTHON "$WORKSPACE/gv_tools/examples/plot_postprocessed_mrr.py" \
     /Volumes/36TB/MRR/TAMU-CC/reprocessed/nc_files/nc_files_c01_mom/2023/08/22 \
     "$WORKSPACE/MRRPro_TAMUCC_20230822.png"

The example appends the detected product code, producing
``MRRPro_TAMUCC_20230822_mom.png``. Spectral and original products use
``_spc`` and ``_org`` respectively.

Runnable Python examples are kept in the project-level ``examples`` folder.

.. literalinclude:: ../examples/quickstart.py
   :language: python
   :linenos:

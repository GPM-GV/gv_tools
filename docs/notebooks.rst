Notebooks
=========

Release notebooks are kept in the project-level ``notebooks`` folder. Start
with ``check_gv_tools.ipynb`` to configure, load, and plot every supported
instrument family using explicit input and figure paths.

The validation notebook defines ``WORKSPACE``, ``PACKAGE_DIRECTORY``, and
``OUTPUT_DIRECTORY`` on separate configuration lines. ``OUTPUT_DIRECTORY`` is
set to ``WORKSPACE / "Output"`` so figures are never written inside the package
directory or one of its subdirectories.

* ``check_gv_tools.ipynb`` (complete instrument ingest and plotting check)
* ``Ingest_WSR88D.ipynb``
* ``MRRPro_Postprocessed_Ingest_and_Display.ipynb`` (hourly collection ingest
  and extensively configurable time-height displays)
* ``Upper_Air_Sounding_Downloads.ipynb`` (download, decode, and Skew-T test)

The installed location can be discovered without hard-coded paths:

.. code-block:: python

   from pathlib import Path

   notebooks = Path("notebooks")

The notebooks may be launched from any directory. Input and output locations
are controlled by the clean variables in each configuration cell.

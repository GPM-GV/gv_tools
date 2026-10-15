GV Tools
========

GV Tools reads, normalizes, validates, writes, and plots NASA GPM Ground
Validation instrument data. Its public interface is divided by task, like
ARM Py-ART, so users can discover related operations in one place.

.. code-block:: python

   import gv_tools

   files = ["/data/PIERS0042/PIERS0042_Parsivel_20260810_daily.zip"]
   parsivel = gv_tools.io.read_parsivel(files)

.. toctree::
   :maxdepth: 2

   userguide
   mrr
   piers
   process_parsivel
   py_2dvd/index
   api/index
   notebooks
   examples
   architecture
   metadata
   output-conventions

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

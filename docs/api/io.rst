gv_tools.io
===========

.. automodule:: gv_tools.io
   :members:
   :undoc-members:
   :show-inheritance:

2DVD
----

Use ``gv_tools.io.read_2dvd`` for the supported public reader. It returns a
pandas DataFrame containing one row per detected drop.

.. automodule:: gv_tools.io.py_2dvd
   :members: ingest_raw, date_from_filename

Tipping-bucket gauges
---------------------

.. automodule:: gv_tools.io.gauge
   :members: read_gauge, read_tipping_bucket, tipping_bucket_rain

Parsivel decoder
----------------

.. automodule:: gv_tools._parsivel
   :members: iter_days, run, integral_parameters, get_parsivel_classes, terminal_velocity,
      velocity_filter_mask, parse_telegram_line, filename_stamp, discover_input_dates,
      load_tables, get_integral_parameters, ParsivelClasses

Parsivel processing
===================

``gv_tools.io.read_parsivel`` decodes OTT Parsivel / Parsivel2 telegrams from
APU and PIERS loggers and integrates the 32 x 32 raw spectrum (OTT field 93)
into one-minute drop-size-distribution products. This page documents what the
decoder accepts and the formulas it uses (changed in 0.65.0).

Inputs
------

* Plain ``.csv``/``.dat`` files and the ``.csv``/``.dat``/``.txt`` members of
  ``.zip`` archives, read in memory. No scratch files are written.
* File names may be anything. Each source is first scanned for its earliest
  and latest telegram stamp (a fast look at the 14 characters before every
  ``;``); sources are decoded in that order and a day is produced once no
  unread source can hold a telegram for it. A file holding parts of several
  days, or named for a day other than its content, is handled correctly.
  Inside a file whose stamps never go backwards a day is produced as soon as
  the file is 30 minutes past the day's end, so about one day of telegrams
  (about 2 kB each) is held in memory however long the file is; a file out of
  time order is held whole until it has been read.
* When a *directory* is read with ``start_date``/``end_date``, packet files
  (10-, 12- or 14-digit stamps) and ``*_daily`` files named more than a day
  outside the window are skipped without being opened; files you name
  explicitly are always scanned. Inside a file, lines stamped more than 30
  minutes outside the window are skipped before their spectrum is decoded
  (they are not counted in ``rejected_lines``), and a time-ordered file is
  closed at its first stamp after the window.
* Daily files and their packets may be mixed: every telegram is counted once
  (``duplicate_telegrams`` reports repeats, ``conflicting_telegrams`` reports
  equal time stamps with different spectra -- the first read is kept and a
  warning is logged). The Parsivel cannot send telegrams less than 10 s
  apart, so an equal spectrum stamped within 2 s of another is the same
  telegram logged twice and is counted once as well -- unless the pair
  fills a gap of about two intervals, as when a telegram stamped late lands
  just before the next one.
* A telegram stamped before 2005 or more than 30 days ahead of the
  computer's clock comes from a logger whose clock was not set; it is
  rejected (``rejected_lines``) rather than turned into a day of its own.

A telegram is accepted only when it is complete: a valid 14-digit
``YYYYMMDDhhmmss`` stamp, ``;``, exactly ``spectrum_offset`` header fields (9
by default) followed by 1024 non-negative integer counts, with an optional
trailing comma. A telegram with one header field more or less would otherwise
be read with every count shifted into the neighbouring diameter class, so it
is rejected and a warning reports the field counts seen; set
``spectrum_offset`` (or ``strict_fields=False``) for a different logger
layout. A missing final newline, a stray ``"`` or a non-UTF-8 byte costs at
most the telegram that contains it (``rejected_lines``, counted once per
file and reported for every day the file's stamps cover, even when none of
its telegrams could be used). Two telegrams run together on one line are split at their time stamps,
and text before a time stamp is ignored.

Time base and sample duration
-----------------------------

A telegram holds the drops counted during the measuring interval that ends at
its stamp. The interval is inferred for every telegram from its neighbours:
the largest spacing of at least 10 s (the shortest Parsivel interval) that at
least 80 % of the surrounding spacings are whole multiples of (within 1 s) and
that itself occurs at least three times (15 spacings before, after and around
the telegram are tried, and the answer may not exceed the telegram's own
spacing). Lost telegrams only lengthen spacings, so this holds for any loss
rate, and a lasting change of the logger interval is followed within a
telegram or two. A telegram whose own neighbourhood is inconclusive -- a stamp
a few seconds late, a short irregular burst -- takes the interval of the
nearest telegram (within 30) that has one, so stamps up to 5 s late do not
change the result (tested at 10, 30 and 60 s with 30 % of the telegrams
lost). When nothing nearby can tell, the most common interval of the
surrounding telegrams, then the previous day's, then that of later telegrams
is used; failing that 60 s is assumed with a warning.

A run of fewer than about 20 telegrams at a longer interval inside a stream at
a shorter one (ten 60 s telegrams in a 10 s day, say) looks exactly like lost
telegrams and gets the shorter interval. ``telegram_interval_s`` fixes the
interval when you know it.

Each telegram is counted in the UTC minute holding the centre of its
interval (``stamp - interval / 2``); minutes are labelled by their start. A
60 s telegram stamped 12:01:00 therefore belongs to 12:00, and one stamped
00:00:13 to 23:59 of the previous day. ``time_binning="stamp"`` bins by the
stamp instead, as 0.50.0 did.

A day product (``gv_tools.io.ParsivelAdapter.read``) has all 1440 minutes;
``read_parsivel`` returns the span from the first to the last minute with a
telegram. Minutes without telegrams are **missing** (NaN) with
``telegram_count == 0`` -- not dry. ``sample_duration`` is the sum of the
intervals of the minute's telegrams and is the time used in every rate, so a
minute holding 3 of its 6 telegrams is not reported at half its rain rate.

Class definitions
-----------------

``classes="ott"`` (default) uses the OTT Parsivel2 class centres and widths
from the instrument manual (``data/parsivel/diameter.dat`` and
``velocity.dat``). ``classes="legacy"`` reproduces the 0.50.0 tables
(``parsivel_diameter_py.txt``), whose diameters and widths are the OTT values
multiplied by 1.03 and whose velocity centres between 0.85 and 3.8 m s-1 differ
from the OTT classes; it also removes one isolated cell (9.5 mm at 4.4 m s-1)
from the bundled conditional matrix. It reproduces the 0.50.0 *tables*, with
the velocity-axis error fixed, not 0.50.0's *output*. A 3 % size scaling
raises rain rate by about 9 % (D\ :sup:`3`) and Z by about 0.8 dB
(D\ :sup:`6`).

Velocity-diameter filter
------------------------

Counts are kept where the velocity-class centre lies within
``(1 +/- velocity_filter) x Vt(D)`` (default +/-50 %) and the diameter-class
centre is below ``max_diameter_mm`` (default 10 mm). ``Vt(D)`` is the
Gunn and Kinzer (1949) terminal speed near sea level, interpolated from
``data/parsivel/terminal_velocity_gunn_kinzer.txt`` with a ``D**2`` (Stokes)
tail below 0.1 mm and the 9.175 m s-1 plateau above the table. The filter
removes splashing, margin fallers and most non-rain particles; use
``velocity_filter=None`` to keep every velocity.

Formulas
--------

With ``n_ij`` the filtered counts in diameter class *i* and velocity class
*j* during ``dt`` seconds:

.. math::

   A_i &= 180\,\mathrm{mm} \times (30\,\mathrm{mm} - D_i/2)
       \quad\text{(effective sampling area)}\\
   N(D_i) &= \frac{1}{\Delta D_i}\sum_j \frac{n_{ij}}{A_i\,\Delta t\,V_{ij}}
       \quad [\mathrm{m^{-3}\,mm^{-1}}]\\
   M_k &= \sum_i N(D_i)\,D_i^k\,\Delta D_i \quad [\mathrm{m^{-3}\,mm^k}]\\
   \mathrm{LWC} &= \frac{\pi}{6}\,\rho_w\,M_3 \quad [\mathrm{g\,m^{-3}}],\qquad
   Z = M_6 \quad [\mathrm{mm^6\,m^{-3}}]\\
   R &= \frac{3600}{\Delta t}\sum_{i,j} \frac{\pi D_i^3/6}{A_i}\,n_{ij}
       \quad [\mathrm{mm\,h^{-1}}]\\
   D_m &= M_4/M_3,\qquad
   \sigma_m = \sqrt{\frac{\sum_i N(D_i)\,D_i^3\,(D_i - D_m)^2\,\Delta D_i}{M_3}},\qquad
   N_w = \frac{4^4}{6}\,\frac{M_3^5}{M_4^4}

``V_ij`` is the measured velocity-class centre ``V_j`` (``fall_speed="measured"``,
default) or the terminal speed ``Vt(D_i)`` (``fall_speed="theoretical"``). The
rain rate is the volume flux through the beam and does not depend on that
choice. ``dBZ`` is ``10 log10(Z)`` and is NaN when ``Z = 0``; ``Dm``,
``sigma_m``, ``Nw``, ``Dmax`` and ``mean_fall_speed`` are NaN for observed
minutes without drops, while counts, concentration, LWC, Z and rain rate are 0.

Outputs
-------

.. list-table::
   :header-rows: 1

   * - Variable
     - Units
     - Meaning
   * - ``drop_size_distribution``
     - m-3 mm-1
     - N(D) on ``drop_diameter`` (with ``drop_diameter_width``)
   * - ``drop_size_moment``
     - m-3 mm^n
     - M0 ... M7
   * - ``precipitation_rate``
     - mm h-1
     - flux rain rate R
   * - ``liquid_water_content``
     - g m-3
     - LWC
   * - ``reflectivity_factor``
     - mm6 m-3
     - Z
   * - ``radar_reflectivity``
     - dBZ
     - 10 log10 Z
   * - ``number_concentration``
     - m-3
     - M0
   * - ``mass_weighted_mean_diameter``
     - mm
     - Dm
   * - ``mass_spectrum_width``
     - mm
     - sigma_m (a standard deviation; 0.50.0 stored the variance)
   * - ``normalized_intercept_parameter``
     - m-3 mm-1
     - Nw
   * - ``maximum_drop_diameter``
     - mm
     - centre of the largest class with drops
   * - ``mean_fall_speed``
     - m s-1
     - count-weighted mean velocity-class centre
   * - ``drop_count``
     - 1
     - filtered drops
   * - ``raw_drop_count``
     - 1
     - particles before the filter
   * - ``telegram_count``
     - 1
     - telegrams in the minute
   * - ``sample_duration``
     - s
     - telegram_count x telegram interval
   * - ``raw_spectrum`` (optional)
     - 1
     - per-minute raw counts, ``include_spectrum=True``

Example
-------

.. code-block:: python

   import gv_tools

   day = "/gv_raid/PIERS_Rawdata/PIERS0042/2026/08/10"
   nxt = "/gv_raid/PIERS_Rawdata/PIERS0042/2026/08/11"   # its first packet holds 23:50-23:59
   ds = gv_tools.io.read_parsivel(
       [day, nxt], start_date="2026-08-10", end_date="2026-08-10",
       classes="ott", fall_speed="measured",
   )
   wet = ds.where(ds.telegram_count > 0)

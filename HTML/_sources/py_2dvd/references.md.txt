# References and provenance

**R1.** Tokay, A., A. Kruger, and W. F. Krajewski, 2001: *Comparison of Drop Size
Distribution Measurements by Impact and Optical Disdrometers*. Journal of Applied
Meteorology, **40**, 2083–2097.
[AMS article](https://journals.ametsoc.org/view/journals/apme/40/11/1520-0450_2001_040_2083_codsdm_2.0.co_2.xml).
DOI: 10.1175/1520-0450(2001)040<2083:CODSDM>2.0.CO;2.
Provides context for optical/impact disdrometer DSD and rainfall comparisons.

**R2.** Kruger, A., and W. F. Krajewski, 2002: *Two-Dimensional Video Disdrometer:
A Description*. Journal of Atmospheric and Oceanic Technology, **19**, 602–617.
[AMS article](https://journals.ametsoc.org/abstract/journals/atot/19/5/1520-0426_2002_019_0602_tdvdad_2_0_co_2.xml).
DOI: 10.1175/1520-0426(2002)019<0602:TDVDAD>2.0.CO;2.
Instrument design and operation; the project files, not this paper, define the
particular text-column positions parsed by this package.

**R3.** Tokay, A., W. A. Petersen, P. Gatlin, and M. Wingo, 2013: *Comparison of
Raindrop Size Distribution Measurements by Collocated Disdrometers*. Journal of
Atmospheric and Oceanic Technology, **30**, 1672–1690.
[AMS article](https://journals.ametsoc.org/abstract/journals/atot/30/8/jtech-d-12-00163_1.xml).
DOI: 10.1175/JTECH-D-12-00163.1.
Context for collocated-instrument DSD and rainfall differences; lite does not
silently adopt an additional paper-specific filter.

**R4.** Williams, C. R., et al., 2014: *Describing the Shape of Raindrop Size
Distributions Using Uncorrelated Raindrop Mass Spectrum Parameters*. Journal of
Applied Meteorology and Climatology, **53**, 1282–1296.
[AMS article](https://journals.ametsoc.org/view/journals/apme/53/5/jamc-d-13-076.1.xml).
DOI: 10.1175/JAMC-D-13-076.1.
Supports use of mass-spectrum mean diameter and standard deviation. Lite computes
these statistics directly; it does not implement the paper's full retrieval or
its decorrelated parameterization.

**Project format/algorithm sources.** The supplied `2DVD_progs/load_drop_file.pro`
defines the clock-string indices and header count. The supplied `dropbydrop.f`
and `intr.f` define the historical QC/interpolation ordering. The predecessor's
validated input precision, bins and output mask are retained for continuity;
they are not represented as journal requirements. `tervel.dat`, `oblateness.txt`
and `2dvd_diameter020.txt` are the bundled numerical inputs. The full
`py_2dvd` 0.11.1 literature outputs provide a regression reference. Lite imports
none of that package and carries no FORTRAN executable or RainNASA integral branch.

**Reference verification.** Bibliographic records and available publisher/repository
summaries were checked during this cleanup. Direct full-text publisher requests
were access-restricted. This guide gives an explicit, independently testable
unit derivation and avoids claims about unverified equation numbers or verbatim
paper text. Original derivations and numerical tests accompany the implementation.

**AI provenance.** Prepared with OpenAI Codex assistance, 2026-09-11. The exact
service model identifier is not asserted. AI authorship metadata is not scientific
validation. The distribution records tests and sample comparisons in VALIDATION.json.
The rewrite was formatted with Black and checked with Ruff for Python errors.


Version 0.1.2 exports separate measured/terminal files with explicit velocity names. See README for the eight new save_products return keys.

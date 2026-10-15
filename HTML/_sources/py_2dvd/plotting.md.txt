# Plotting and command-line behavior

## Integral figure

The fixed eight panels show rain rate, dBZ, liquid water content, Dm/DMax,
accepted count, number concentration, mass-spectrum spread and DMin. Linear
reflectivity remains in the Dataset but is not plotted. Blue Dm and orange-red
DMax are fully opaque. The only multi-curve panel has a legend; the overall
heading supplies the common literature method, selected velocity, site and date.

Options accepted by plot_integral_parameters:

| Keyword | Default | Meaning |
|---|---|---|
| velocity | measured | existing velocity coordinate to display |
| output_dir | None | output root above Plots; None means no file |
| figsize | (14, 14) | figure width/height in inches |
| colors | None | mapping from physical variable names to Matplotlib colors |
| ylimits | None | mapping from panel's first variable to (minimum, maximum) |
| time_range | None | two increasing timestamps; otherwise raw-record window |
| valid_only | True | mask minutes failing the reporting rule |
| linewidth | 1.5 | line width in points |
| dpi | 150 | resolution of saved PNG |
| rc_params | None | scoped Matplotlib font/style overrides |
| show | False | call pyplot.show after optional saving |

For the shared Dm/DMax panel, set ylimits with `mass_weighted_diameter`; the
panel has one common vertical scale. Masking inserts missing values so plotted
lines do not bridge excluded minutes. Setting valid_only=False displays stored
values without the reporting threshold; it does not change calculation or QC.

## DSD figure

Options are velocity, output_dir, time_range, valid_only, dpi, rc_params and show
as above, plus figsize=(12,6), diameter_range=(0,5),
concentration_range=(1,10000) and cmap='dsd'. Supply a registered Matplotlib
colormap name to replace the inherited DSD palette.

The stored time-by-diameter slice is transposed for pcolormesh, whose rows are
diameter and columns time. One extra time edge closes the final minute; stored
lower/upper diameter edges define the actual cells. Values are neither
interpolated nor smoothed. Nonfinite and nonpositive cells are masked before
LogNorm. Colorbar limits are physical concentrations, not log10 values. Values
outside the chosen color limits saturate at the palette ends; they are not
removed from the Dataset. Limit choices can conceal variation, so report them
when comparing figures.

## Style and figure lifecycle

Default fonts are 14-point general text, 18-point axis titles, 15-point labels,
13-point ticks, 12-point legends and 20-point figure titles. An rc_context scopes
changes to the plotting call. `rc_params={'font.size':16}` changes general text;
explicit axes/tick/legend settings remain independently configurable.
Constrained layout allocates room for titles, labels and colorbars. Functions
return live Figure objects; close them after saving when producing many plots.

Output filenames include site/day/velocity/kind. Measured and terminal plots can share the same output root without overwriting each other.

## CLI stages

Processing reads raw input, calculates both products once, and saves both
velocity choices. Plotting reads a previously saved lite NetCDF, loads the arrays,
closes the file, then renders both figures. It does not reopen the original drops
or recalculate moments. Root .py scripts and installed console commands call the
same cli.py functions. Shell options are parsed before work begins.

```tcsh
setenv WORKSPACE /Users/dwolff/Desktop/Work/py2DVD_Wolff
cd "$WORKSPACE"
~/anaconda3/bin/python py_2dvd_lite/process_2dvd_lite.py /Volumes/TBW/distro/2dvd/2dvd_sn37/ascii/V23022.drops.zip
~/anaconda3/bin/python py_2dvd_lite/plot_2dvd_lite.py Output/NetCDF/2023/01/WFF_2023_0122_2DVD_measured_velocity.nc --velocity measured --plot-config py_2dvd_lite/examples/plot_config.json
```

The JSON rain/dsd objects supply plotting keyword options. rcParams is shared.
Velocity, output directory and interactive display belong to CLI options; do not
repeat them inside JSON. Unknown or conflicting keywords cause an error rather
than silently changing the selected branch. --show displays figures after saving;
otherwise the CLI uses Agg and closes figures. A second-figure error can leave
an already-saved first PNG; exporting two figures is not an atomic transaction.
Fix the configuration and rerun. Handled failures exit 2; success returns 0.


Version 0.1.2 exports separate measured/terminal files with explicit velocity names. See README for the eight new save_products return keys.

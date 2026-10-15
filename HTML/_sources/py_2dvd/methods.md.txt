# From drops to integral parameters and DSD

## Selection and historical compatibility

The physical calculation is the literature formulation. To isolate this code
cleanup from a change in sample selection, preprocessing retains the full package's
validated conventions from the supplied files. These conventions are explicitly
**not attributed to a journal paper**:

1. Reconstruct diameter from volume using `(6 V / pi)**0.333`, the exponent in
   `dropbydrop.f`. It is slightly different from an exact cube root.
2. Interpolate terminal velocity with `intr.f`'s three-nearest-point quadratic
   interpolation. Ties retain the earlier table row; out-of-range queries
   extrapolate. Convert `tervel.dat` velocities from cm/s to m/s.
3. Apply strict measured-velocity bounds: 0.5 to 1.5 times the interpolated
   terminal speed. For reported diameter at least 6 mm, overwrite the terminal
   speed with `9.65 - 10.3 exp(-0.6 D)` afterward; the bounds retain their earlier
   values, reproducing the supplied pipeline's order of operations.
4. Reject the first backward hour/minute jump and every later row. A backward
   second within the same minute does not trigger this particular legacy rule.
   Require reconstructed diameter at most 10 mm. The oblateness lookup is a
   diagnostic, not an additional selection condition.
5. After selection, round diameter, area and both velocities to three decimals,
   cast to float32, then back to float64 for integration. This models the earlier
   intermediate text file and single-precision read-in. It is retained to avoid
   changes at bin boundaries, not because the literature requires rounding.

Table authorship beyond the supplied project is not assumed. All three numerical
tables are bundled and hashed. No RainNASA integral calculation is carried into
lite; the old preprocessing/reporting conventions remain visible and auditable.

## Sampling-volume normalization

For an accepted drop j, the code uses its supplied effective sampling area A_j,
not a single nominal instrument area. Convert `sampling_area_mm2` to m² by 1e-6.
Let v_j be measured or terminal velocity in m/s and T=60 seconds. The sampled
volume is A_j v_j T, in m³. One detected drop contributes

```text
w_j = 1 / (A_j v_j T)                         [m^-3]
```

This discrete sampling-volume interpretation connects counts to concentration.
The instrument and DSD literature provide the context [R1–R3]; the explicit unit
calculation here documents this implementation. There is no second geometric
area correction, dead-time correction, gamma fit or unmeasured-small-drop
extrapolation. Every minute is treated as 60 seconds of exposure; absent records
do not establish that the instrument was operating.

## Moments, mass, rain and diameter statistics

With diameter D_j in mm, define M_k=sum(D_j^k w_j) over drops in the minute.
These sums use **individual diameters**; substituting bin centers changes higher
moments and is not the operation implemented here.

| Parameter | Discrete calculation | Units |
|---|---|---|
| number_concentration | M_0 | m^-3 |
| reflectivity | M_6 | mm^6 m^-3 |
| reflectivity_dbz | 10 log10(M_6), for M_6 > 0 | dBZ |
| liquid_water_content | (pi/6) × 1e-3 × M_3 | g m^-3 |
| mass_weighted_diameter | M_4 / M_3 | mm |
| diameter_std | sqrt(sum((D_j−Dm)^2 D_j^3 w_j) / M_3) | mm |
| minimum_diameter, maximum_diameter | smallest/largest accepted D_j | mm |
| drop_count | number of accepted drops | 1 |

Liquid water content assumes density 1000 kg/m³. In the code, a drop's volume
is `(pi/6)*(D_mm*1e-3)^3` in m³, multiplied by density and concentration, then
by 1000 to convert kg/m³ to g/m³. `diameter_std` is the **mass-spectrum** spread,
not the ordinary count-weighted standard deviation; see Williams et al. [R4].
Linear reflectivity is the liquid-water Rayleigh D^6 moment, not a Mie or
polarimetric radar observable. It remains in the data but is omitted from plots.

Rain rate is a volume flux through the sampled area:

```text
R = 3.6e6 × sum[(pi/6) × (D_j × 1e-3)^3 / (A_j × 60)]   [mm h^-1]
```

The inner quantity has units m/s; 3.6e6 converts m/s to mm/h. Equivalently,
R is proportional to sum(D_j³ v_j w_j), and v_j cancels for each drop because
w_j contains 1/v_j. Thus measured and terminal branches have the same rain rate
for identical selected drops, while concentration, water content, reflectivity
and mass-weighted statistics can differ. Neither Dm nor its variance is obtained
by fitting a distribution shape. Literature/RainNASA numerical agreement in the
full project does not independently validate the shared physical assumptions.

## DSD and raw counts

Nominal centers use the first 50 rows of `2dvd_diameter020.txt`: 0.1, 0.3, ..., 9.9 mm.
The first two table columns give centers and widths; the additional table column
is not used for velocity or normalization. Membership edges retain successive
float32 additions of 0.2 mm for compatibility. Bins are [lower, upper); the last
upper edge is slightly below 10 mm and is excluded. Normalization uses nominal
width 0.2 mm, not the tiny differences between stored float32 edges.

```text
bin_drop_count(t,i) = number of selected drops in minute t and bin i
N(D_i,t) = sum[w_j for drops in that minute/bin] / 0.2    [m^-3 mm^-1]
```

Raw count is shared by both velocity choices. Concentration is velocity-dependent.
When all selected drops lie inside the bins, sum(N(D_i) × 0.2) equals total number
concentration. A selected drop at the final excluded edge contributes to the
individual-drop integrals but not the DSD; the rules and stored counts expose
that inherited boundary case. Bin-center integration of DSD need not exactly
reproduce the individual-drop higher moments.

## Missing data, masks and outputs

The time coordinate contains 1440 minutes from the filename date. Minutes with no
accepted drops have zero counts and DSD, but NaN bulk values. Nonpositive Z has
NaN dBZ. Zero mass has undefined Dm/spread. `raw_drop_count` distinguishes raw
records from accepted counts. A full-day absence does not prove zero rainfall.
`output_valid` retains the previous reporting rule: more than ten accepted drops
and at least 0.01 mm/h. Values outside that mask remain in the products; plots
mask them by default. No interpolation bridges masked minutes.


Version 0.1.2 exports separate measured/terminal files with explicit velocity names. See README for the eight new save_products return keys.

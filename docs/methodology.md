# Measurement-driven Cochlea Generator — v0.37.0

This Blender add-on creates a comparative cochlear endocast from published
measurements. It is intended for morphology visualization, not histology or
patient-specific reconstruction.

All thirteen generated specimens use the same measurement-to-mesh solver and
the same morphology defaults. Seven original sources are currently available
for overlay validation, including the user-imported Vaquita. The solver treats
`Ch` as measured external cochlear height; `Ch/#T` remains a derived ratio and
is not mistaken for centerline rise per revolution.

v0.29 removes default artificial turn fusion and reduces modiolar inflation.
The canal cross section is approximately round, leaving more of the measured
`Ch` available for genuine centerline climb. Adjacent whorls therefore retain
deep, legible grooves rather than voxel-merging into one inflated mass. Lateral
tube fatness, the measured external envelope, and the sharp open basal rim are
preserved.

v0.30 tightens the shared apical termination without adding angular sweep or
changing measured `#T`. A smaller helicotrema clearance, stronger terminal
taper, and short centripetal cap curl make the final tip wrap inward like the
reference endocasts while keeping the separated-whorl packing from v0.29.

v0.31 replaces the collar-like basal flare join with one C2-continuous shared
transition. Surface detail also fades in gradually after the inlet, preventing
a circumferential seam. The turn-count noodle now begins at the anatomical
spiral origin, excludes the unmeasured flare, and has no separate apical marker
ball.

v0.32.1 keeps the collapse-decimated delivery pipeline but restores the exact
v0.31 apical construction. The experimental transported/shortened cap and
automatic clearance adjustment were rolled back because they damaged Blue
whale and several other otherwise-correct tips. Vaquita retains its small local
wrinkle for optional hand smoothing.

v0.33 adds an optional visualization shell for transparent/rim-shaded close-up
use. The approved v0.32.1 outer endocast is preserved vertex-for-vertex, while
a second sweep at 60% of the local canal radius creates a continuous inner
surface. A short shared quarter-round lip joins that liner to the existing
basal boundary, and the lumen closes smoothly at the apex. This is a rendering
aid rather than a claim about measured bony wall thickness; the source
workbooks contain no wall-thickness field. The same ratio and construction are
used for every specimen, with no specimen-specific tuning.

v0.34 reverses the basal-lip profile requested during visual review. Instead of
shrinking into a recessed chamfer, the rim now rolls outward beyond the canal
wall and curls back to the inner liner. The final collapse-decimated boundary
loop is regularized before that roll is built, removing the radial crunchy
folds while preserving its center and average inlet radius. The rest of the
v0.32 outer cochlear body remains unchanged.

v0.35 adds optional organic variation as actual displaced geometry, so it
remains visible with rim shaders that do not accept a normal map. One shared,
deterministic three-scale fBm field supplies broad undulation, mid-scale
variation, and restrained fine grain. The displacement is zero-mean, clamped,
and applied along smooth vertex normals with an RMS amplitude of 0.24% of `Cw`;
the layer wavelengths are also scaled from `Cw`. Fine detail fades around the
outward-rolled inlet, preserving the clean mouth profile. No specimen-specific
surface tuning is used, and the displacement changes no measurement inputs or
polygon counts.

v0.36 changes only the turn-noodle interchange packaging. Each populated turn
range is now a separately named mesh object with exactly one material:
`T00_100`, `T100_150`, `T150_200`, and, where present, `T200_PLUS`. Adjacent
segments reuse identical boundary coordinates, so the noodle remains visually
continuous. This avoids the single-color result produced by importers that
flatten the earlier per-face material assignments. Cochlear geometry is
unchanged from v0.35.

v0.37 simplifies those separately addressable noodles to three possible
ranges: purple `T00_100` for 0–1 turn, orange `T100_200` for 1–2 turns, and
green `T200_PLUS` for any remainder beyond 2 turns. Specimens below or exactly
at 2 turns therefore export only the two populated purple/orange meshes. The
former blue 1–1.5 range is merged geometrically into the orange 1–2 mesh.

## Open these files

- `output/cochlea_normalized_exports_v37_three_section_noodles.blend` — current
  organic hollow cochleas with purple 0–1, orange 1–2, and green 2+ noodles.
- `output/glb_normalized_v37_three_section_noodles_validation.json` — strict
  re-import validation for all 13 current cochlea/noodle pairs.
- `output/cochlea_normalized_exports_v36_segmented_noodles.blend` — prior
  organic hollow cochleas with the superseded four-range noodles.
- `output/glb_normalized_v36_segmented_noodles_validation.json` — strict
  re-import validation for all 13 cochlea/noodle pairs and their section meshes.
- `output/cochlea_normalized_exports_v35_organic_hollow.blend` — prior closed
  hollow visualization shells with subtle physical geometry displacement and
  the earlier single-mesh noodle packaging.
- `output/glb_normalized_v35_organic_hollow_validation.json` — re-import
  validation for all 13 displaced hollow cochlea/noodle pairs.
- `output/cochlea_normalized_exports_v34_hollow.blend` — optional closed hollow
  visualization shells with the smoothed outward-rolled lip and no organic
  displacement; this remains the perfectly smooth fallback.
- `output/glb_normalized_v34_hollow_validation.json` — re-import validation for
  all 13 hollow cochlea/noodle pairs.
- `output/cochlea_normalized_exports_v32_with_original_sources.blend` — preferred
  review file with seven untouched source meshes and captured user transforms.
- `output/cochlea_normalized_exports_v32.blend` — generated meshes; measurement
  noodles remain present but are hidden in the review scene.
- `output/glb_normalized_v32_validation.json` — GLB re-import validation.
- `presets/source_overlay_transforms_user_2026-07-31.json` — durable source
  location/rotation/scale capture, including mirrored scales.

Original open-end GLB exports are in `output/glb_normalized_v32/`. Smooth
inner-lined variants are in `output/glb_normalized_v34_hollow/`; the current
geometry-displaced variants are in `output/glb_normalized_v35_organic_hollow/`.
The current delivery is in `output/glb_normalized_v37_three_section_noodles/`,
with the same filenames and cochlea geometry but simplified section-mesh noodle
assets. v0.32 cochlea shells are collapse-decimated to 25,000 triangles; the
hollow assets retain that exterior and add the inner liner, producing roughly
53–62k triangles. Blender coordinates are millimetres; GLB exports use metres
while preserving physical size.

## Shared geometry model

The construction priority is:

1. `#T` sets the angular sweep exactly.
2. `Cl` solves the shared spiral's radial contraction; it never invents turns.
3. `Cw` sets external width exactly; `Ch` sets the complete external height.
4. `W2` softly informs basal planform without turning the whole cochlea oval.
5. `ITD` is retained as a validation measurement, not a hidden morphology
   switch.

The canal radius is derived by one shared equation from `Cw` and `W2`, because
these scans are bony-labyrinth endocasts rather than thin membranous ducts. The
same tapered cross section, vertical tiering, basal hook, ridges, and surface
variation are applied to every specimen. Turn fusion defaults to zero.
Reference meshes are
validation targets only; their names and transforms do not enter the solver.

The visible gap where the basal segment approaches the next whorl is not an
independent measurement. It emerges from the measured `Cl`, `#T`, and `Cw`,
the shared Cw/W2-derived canal thickness, and the FC-driven flare. v0.24 keeps
that measurement-driven packing but adds one short exposed inlet neck so the
flare cannot close the entry portal merely through voxel fusion.

The v0.18-v0.20 solver misread axial pitch as a literal helical pitch. It made
the centerline climb the full `Ch`, then added the endocast canal thickness
outside that interval. This double-counted height and created the repeated
stair-step gaps visible in side profile. A small tube-thickness adjustment could
not fix a gap already encoded in the centerline.

v0.21+ solves centerline rise against the completed mesh: canal thickness stays
physical, while the external Z envelope converges on `Ch`. The axial-pitch
column remains reported exactly as the paper defines it, `Ch/#T`, but it is not
used as a hidden centerline measurement. No species name or source transform
enters the calculation.

v0.22 restores the Squalodon `Ch = 4.98 mm` value from the project's
authoritative Measurements tab. The supplemental workbook's USNM 10484 row
reports `2.58 mm`, but that value conflicts with both the Measurements tab and
the approximately 4.75 mm aligned cochlear envelope in the exact reference
endocast. This is an input-provenance correction; the shared solver and all
morphology defaults are unchanged.

The base v0.32 result is one connected mesh with exactly one intentional open
boundary loop at the basal inlet. The optional v0.33 visualization shell joins
that loop to its inner liner and is therefore one closed manifold with no open,
wire, or branching edges. Neither version is assembled from tori, cylinders,
free-standing ribbons, or a separate modiolar cone.

## Measurement mapping

| Field | Generator use |
| --- | --- |
| `Cl` | Centerline-length constraint on radial contraction |
| `Cw` | Exact external major width |
| `W2` | Shorter basal-turn diameter perpendicular to Cw; soft planform and shared tube-radius input |
| `Ch` | Exact external cochlear height; with #T, defines the reported ratio `Ch/#T` |
| `#T` | Exact angular sweep |
| `ITD` | Reported as a centerline-packing validation landmark |
| `SBLr` | Longitudinal extent of the integrated inner shoulder |
| `GAN` | Metadata only; no detached ganglion primitive |
| `FC` | Shared influence on the flare approaching the sharp open inlet; never a detached primitive |

Axial pitch (`Ch / #T`) is a derived shape ratio, not a separately measured
centerline pitch. Other derived workbook fields such as basal ratio, cochlear
slope, ITDr, GANr, and SBLr remain QA summaries and do not require extra
per-specimen controls.

`presets/reference_specimens.json` contains only identity, source metadata, and
published measurements for cf. Aetiocetus, Echovenator, Scaphokogia,
Semirostrum, Squalodon, and Zygorhiza. It deliberately contains no tube-radius,
taper, stacking, tiering, fusion, fullness, hook, or packing overrides.

## Install as a Blender add-on

1. Open **Edit → Preferences → Add-ons**.
2. Choose **Install from Disk** and select `cochlea_generator.py`.
3. Enable **Measurement-driven Cochlea Generator**.
4. Open the 3D Viewport sidebar and select **Cochlea**.
5. Load a measurement preset or enter custom measurements, then choose
   **Generate Cochlea**.

The add-on was validated with Blender 5.1.2.

## Headless generation

From this directory:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background \
  --factory-startup \
  --python tools/export_normalized_glbs.py
```

Rebuild the source-overlay scene with all captured transforms using:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background \
  --factory-startup \
  --python tools/add_source_overlays_v32.py
```

The overlay step restores the saved location, rotation mode, rotation, and
scale for all seven available sources. Translation is retargeted only by any
change in the generated pair's layout position.

Build and export the current organic hollow visualization shells from the
approved v0.32 delivery using:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background \
  --factory-startup \
  --python tools/build_inner_lined_exports.py
```

The post-process does not overwrite the original v0.32 Blender file or GLBs.
Use `--no-organic-displacement` to rebuild the hollow geometry without physical
surface variation.

## Turn-count noodle inspection

Build a non-destructive inspection file with intact cochlear meshes and a
color-coded centerline noodle marking 1.0 and 2.0 turns:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background \
  --python tools/build_turn_noodle_inspection.py
```

The resulting `output/cochlea_generator_v24_turn_noodles.blend` counts turns
from the anatomical spiral origin along the exact procedural centerline; the
basal flare is excluded. Each noodle is one continuous path, with color
transitions for 0–1, 1–2, and any 2+ apical remainder. Its diameter is 30% of
the local cochlear-tube diameter, and it has no separate terminal ball.
Generated cochlear meshes remain intact and unsegmented. Reference collections
are retained with their manual transforms unchanged, but start hidden so the
noodles are easy to read. The current transitions are purple 0–1, orange 1–2,
and green for any 2+ apical remainder.

## Current limitations

- The generator does not include the vestibule, aqueducts, or semicircular
  canals.
- The optional source segments are spatial visualization crops, not anatomical
  dissections; the untouched originals remain embedded and visible.
- The workbook has no direct endocast canal cross-section diameter, so fatness
  is inferred by the documented shared Cw/W2 equation.
- `tools/compare_vertical_spacing.py` renders shared envelope/tube-height
  alternatives used to diagnose the Ch interpretation.
- The downloaded reference identities were checked against their specimen
  records. The source overlays are exact specimen-level references, not
  cross-specimen stand-ins. Squalodon's
  height follows the project Measurements tab because of the documented `Ch`
  discrepancy above.
- ITD conventions are less stable than Cl, Cw, Ch, and #T, so ITD remains a
  soft constraint and achieved spacing is reported.
- Native anatomical side remains `UNKNOWN` unless documented; generated
  comparisons are explicitly right-sided and source meshes are never silently
  mirrored.

Workbook/article source: Racicot et al., “Variation in whale (Cetacea) inner
ear anatomy reveals the early evolution of ‘specialized’ high-frequency
hearing sensitivity,” *Journal of Anatomy* (2025):
<https://pmc.ncbi.nlm.nih.gov/articles/PMC11828743/>.

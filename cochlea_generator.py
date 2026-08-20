"""Measurement-driven procedural cochlea generator for Blender.

The generator treats turn count as the angular sweep and cochlear length as a
constraint on how quickly that sweep contracts toward the apex. Cw fits the
external major width, while Ch fits the complete external cochlear height.
Axial pitch (Ch/#T) is retained as the paper's derived morphometric ratio; it
is not misread as centerline rise. W2 and inter-turn distance remain secondary
packing landmarks rather than specimen-specific shape overrides. A tapered 3D
spiral makes individual turns legible while surface-integrated ridges add
morphological landmarks without separate intersecting primitives.

Install this file as a Blender add-on, or import it from a headless Blender
script.  Coordinates are authored in millimetres; the scene is configured so
one Blender unit displays as one millimetre.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields, replace
from typing import Iterable, Sequence

import bpy
import bmesh
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector


bl_info = {
    "name": "Measurement-driven Cochlea Generator",
    "author": "10k Science",
    "version": (0, 32, 1),
    "blender": (4, 3, 0),
    "location": "3D Viewport > Sidebar > Cochlea",
    "description": "Generate a morphological 3D cochlea from anatomical measurements",
    "category": "Add Mesh",
}


TAU = math.tau
EPSILON = 1e-9
@dataclass(slots=True)
class CochleaParams:
    species_name: str = "Generated Cochlea"
    specimen: str = ""
    cochlear_length_mm: float = 34.13
    cochlear_width_mm: float = 9.05
    basal_width_perp_mm: float = 6.87
    turns: float = 2.0
    cochlear_height_mm: float = 6.77
    interturn_distance_mm: float = 1.85
    secondary_lamina_extent_pct: float = 69.75
    spiral_ganglion_diameter_mm: float = 0.40
    fenestra_area_mm2: float = 8.92
    canal_radius_mm: float = 0.0
    packing_bias: float = 0.0
    canal_thickness_scale: float = 1.00
    apical_taper: float = 0.88
    terminal_taper: float = 0.58
    terminal_curl: float = 0.22
    helicotrema_clearance: float = 0.16
    w2_planform_influence: float = 0.10
    vertical_profile: float = 1.00
    turn_stack_scale: float = 1.00
    turn_tiering: float = 0.55
    ridge_strength: float = 0.090
    ridge_count: int = 4
    sulcus_strength: float = 0.065
    surface_irregularity: float = 0.045
    central_fullness: float = 0.12
    turn_fusion: float = 0.0
    basal_hook: float = 0.34
    canal_height_scale: float = 0.95
    normalize_voxel_size: bool = True
    voxels_across_cochlear_width: int = 90
    voxel_size_mm: float = 0.11
    use_scan_shell: bool = True
    handedness: str = "RIGHT"
    longitudinal_samples: int = 320
    radial_segments: int = 28
    include_secondary_lamina: bool = True
    include_fenestra_collar: bool = True

    @classmethod
    def from_mapping(cls, mapping: dict[str, object]) -> "CochleaParams":
        valid_names = {item.name for item in fields(cls)}
        values = {key: value for key, value in mapping.items() if key in valid_names}
        return cls(**values)


SHARED_MORPHOLOGY_DEFAULTS: dict[str, object] = {
    "canal_radius_mm": 0.0,
    "packing_bias": 0.0,
    "canal_thickness_scale": 1.00,
    "apical_taper": 0.88,
    "terminal_taper": 0.58,
    "terminal_curl": 0.22,
    "helicotrema_clearance": 0.16,
    "w2_planform_influence": 0.10,
    "vertical_profile": 1.00,
    "turn_stack_scale": 1.00,
    "turn_tiering": 0.55,
    "ridge_strength": 0.090,
    "ridge_count": 4,
    "sulcus_strength": 0.065,
    "surface_irregularity": 0.045,
    "central_fullness": 0.12,
    "turn_fusion": 0.0,
    "basal_hook": 0.34,
    "canal_height_scale": 0.95,
    "normalize_voxel_size": True,
    "voxels_across_cochlear_width": 90,
}


BUILTIN_PRESETS: dict[str, dict[str, object]] = {
    "AETIOCETUS": {
        "species_name": "cf. Aetiocetus",
        "specimen": "USNM 256597",
        "cochlear_length_mm": 39.0575,
        "cochlear_width_mm": 11.51,
        "basal_width_perp_mm": 7.58,
        "turns": 2.36,
        "cochlear_height_mm": 7.28,
        "interturn_distance_mm": 1.38,
        "secondary_lamina_extent_pct": 51.29189869,
        "spiral_ganglion_diameter_mm": 0.38,
        "fenestra_area_mm2": 17.42333333,
    },
    "ECHOVENATOR": {
        "species_name": "Echovenator sandersi",
        "specimen": "GSM 1098",
        "cochlear_length_mm": 34.13,
        "cochlear_width_mm": 9.05,
        "basal_width_perp_mm": 6.87,
        "turns": 2.00,
        "cochlear_height_mm": 6.77,
        "interturn_distance_mm": 1.85,
        "secondary_lamina_extent_pct": 69.75,
        "spiral_ganglion_diameter_mm": 0.40,
        "fenestra_area_mm2": 8.92,
    },
    "SCAPHOKOGIA": {
        "species_name": "Scaphokogia cochlearis",
        "specimen": "USNM 452993",
        "cochlear_length_mm": 27.08333333,
        "cochlear_width_mm": 8.81,
        "basal_width_perp_mm": 6.16,
        "turns": 1.89,
        "cochlear_height_mm": 5.74,
        "interturn_distance_mm": 1.23,
        "secondary_lamina_extent_pct": 66.25230769,
        "spiral_ganglion_diameter_mm": 0.33,
        "fenestra_area_mm2": 12.73333333,
    },
    "SEMIROSTRUM": {
        "species_name": "Semirostrum ceruttii",
        "specimen": "SDNHM 65276",
        "cochlear_length_mm": 28.90,
        "cochlear_width_mm": 9.84,
        "basal_width_perp_mm": 7.49,
        "turns": 1.84,
        "cochlear_height_mm": 4.52,
        "interturn_distance_mm": 1.08,
        "secondary_lamina_extent_pct": 90.21,
        "spiral_ganglion_diameter_mm": 0.51,
        "fenestra_area_mm2": 2.55,
    },
    "SQUALODON": {
        "species_name": "Squalodon calvertensis",
        "specimen": "USNM 10484",
        "cochlear_length_mm": 23.33666667,
        "cochlear_width_mm": 8.95,
        "basal_width_perp_mm": 6.19,
        "turns": 1.86,
        # The project Measurements tab is authoritative for the visualization.
        # It reports 4.98 mm, consistent with the aligned source envelope. The
        # supplemental USNM 10484 row's 2.58 mm conflicts with both.
        "cochlear_height_mm": 4.98,
        "interturn_distance_mm": 1.67,
        "secondary_lamina_extent_pct": 70.53,
        "spiral_ganglion_diameter_mm": 0.29,
        "fenestra_area_mm2": 4.10,
    },
    "ZYGORHIZA": {
        "species_name": "Zygorhiza kochii",
        "specimen": "ALMNH 2000 1.2.1",
        "cochlear_length_mm": 42.04,
        "cochlear_width_mm": 13.405,
        "basal_width_perp_mm": 7.08,
        "turns": 2.37,
        "cochlear_height_mm": 7.733333333,
        "interturn_distance_mm": 0.329666667,
        "secondary_lamina_extent_pct": 44.12,
        "spiral_ganglion_diameter_mm": 0.53,
        "fenestra_area_mm2": 13.99,
    },
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value)
    return "_".join(part for part in cleaned.split("_") if part) or "Cochlea"


def _path_length(points: Sequence[Vector]) -> float:
    return sum((points[index] - points[index - 1]).length for index in range(1, len(points)))


def _path_tangents(points: Sequence[Vector]) -> list[Vector]:
    tangents: list[Vector] = []
    for index in range(len(points)):
        if index == 0:
            tangent = points[1] - points[0]
        elif index == len(points) - 1:
            tangent = points[-1] - points[-2]
        else:
            tangent = points[index + 1] - points[index - 1]
        tangents.append(tangent.normalized())
    return tangents


def _parallel_transport_frames(
    points: Sequence[Vector],
) -> tuple[list[Vector], list[Vector], list[Vector]]:
    tangents = _path_tangents(points)
    reference = Vector((0.0, 0.0, 1.0))
    if abs(tangents[0].dot(reference)) > 0.92:
        reference = Vector((1.0, 0.0, 0.0))
    normal = (reference - tangents[0] * tangents[0].dot(reference)).normalized()
    normals = [normal]
    binormals = [tangents[0].cross(normal).normalized()]

    for tangent in tangents[1:]:
        transported = normals[-1] - tangent * normals[-1].dot(tangent)
        if transported.length < 1e-7:
            transported = binormals[-1].cross(tangent)
        normal = transported.normalized()
        binormal = tangent.cross(normal).normalized()
        normals.append(normal)
        binormals.append(binormal)
    return tangents, normals, binormals


def _scale_path_to_spans(
    raw: Sequence[Vector],
    x_span: float,
    y_span: float,
    z_span: float,
    handedness: str,
) -> list[Vector]:
    x_values = [point.x for point in raw]
    y_values = [point.y for point in raw]
    z_values = [point.z for point in raw]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    z_min, z_max = min(z_values), max(z_values)
    x_scale = x_span / max(x_max - x_min, EPSILON)
    y_scale = y_span / max(y_max - y_min, EPSILON)
    z_scale = z_span / max(z_max - z_min, EPSILON)
    y_sign = -1.0 if handedness.upper() == "LEFT" else 1.0

    result = []
    for point in raw:
        x = (point.x - (x_min + x_max) * 0.5) * x_scale
        y = (point.y - (y_min + y_max) * 0.5) * y_scale * y_sign
        z = (point.z - z_min) * z_scale
        result.append(Vector((x, y, z)))
    return result


def _raw_spiral(
    params: CochleaParams,
    radial_power: float,
    mid_bulge: float,
    count: int,
) -> list[Vector]:
    points: list[Vector] = []
    start_angle = math.radians(-32.0)
    vertical_power = _clamp(params.vertical_profile, 0.55, 2.5)
    # A uniform helical ramp reads as one slanted noodle in profile even when
    # its total centerline rise is large. Anatomical cochlear whorls instead
    # read as successive levels around the modiolus. Concentrate the axial rise
    # into one smooth sector of each revolution, leaving a broad low-pitch
    # sector that reads as a tier. Blending with ordinary linear phase keeps Z
    # strictly increasing, so this remains one continuous spiral rather than a
    # stack of disconnected rings.
    tiering = _clamp(_derived_turn_tiering(params), 0.0, 0.96)

    def axial_progress(progress: float) -> float:
        turn_progress = params.turns * progress
        completed_turns = math.floor(turn_progress)
        phase = turn_progress - completed_turns
        # At maximum tiering, roughly one third of the revolution carries most
        # of the axial climb. Centering that sector early in the turn also lets
        # a measured partial apical turn contribute visibly to total height.
        ramp_width = 1.0 - 0.68 * tiering
        ramp_center = 0.30
        ramp_start = _clamp(ramp_center - ramp_width * 0.5, 0.0, 1.0 - ramp_width)
        ramp_phase = _clamp((phase - ramp_start) / max(ramp_width, EPSILON), 0.0, 1.0)
        concentrated = ramp_phase * ramp_phase * (3.0 - 2.0 * ramp_phase)
        phase_progress = phase * (1.0 - tiering) + concentrated * tiering
        return completed_turns + phase_progress

    warped_end = axial_progress(1.0)

    for index in range(count):
        t = index / max(count - 1, 1)
        envelope = max(0.0, 1.0 + mid_bulge * 4.0 * t * (1.0 - t))
        radial_profile = max(0.0, (1.0 - t) ** radial_power * envelope)
        # A swept tube cannot end on the exact mathematical origin without
        # making its transported frame singular.  At that zero-radius point,
        # ordinary cross-section detail collapses into the radial fins seen on
        # Orca, Squalodon, and Xiphiacetus.  Preserve a small helicotrema-like
        # centerline clearance instead.  The hypot blend leaves the basal and
        # middle turns effectively unchanged while smoothly rounding the
        # terminal contraction; normalizing keeps the outer radius at 1.0.
        helicotrema_clearance = _clamp(params.helicotrema_clearance, 0.0, 0.32)
        radial = math.hypot(radial_profile, helicotrema_clearance) / math.hypot(
            1.0, helicotrema_clearance
        )
        theta = start_angle + TAU * params.turns * t
        # A tiny deterministic radial undulation keeps the silhouette organic.
        undulation = params.surface_irregularity * 0.16 * math.sin(theta * 2.0 + 0.7)
        radial *= 1.0 + undulation
        tiered_t = _clamp(
            axial_progress(t) / max(warped_end, EPSILON), 0.0, 1.0
        )
        points.append(
            Vector(
                (
                    radial * math.cos(theta),
                    radial * math.sin(theta),
                    tiered_t**vertical_power,
                )
            )
        )
    return points


def _estimated_interturn_distance(points: Sequence[Vector], turns: float) -> float:
    """Estimate visible planform spacing between adjacent turns.

    Axial stacking is deliberately excluded. Including Z made a taller spiral
    appear more widely packed, which caused the radius fitter to inflate tubes
    sideways and then squash them during the final Ch refit.
    """
    if turns <= 1.0 or len(points) < 8:
        return 0.0
    step = max(1, round((len(points) - 1) / turns))
    distances = []
    # Ignore the exact hook and apex, where landmark measurements are unstable.
    start = max(1, round(step * 0.10))
    stop = min(step, len(points) - step - 1)
    for index in range(start, max(start + 1, stop)):
        first = points[index]
        second = points[index + step]
        delta = first - second
        distances.append(math.hypot(delta.x, delta.y))
    if not distances:
        return 0.0
    # The 80th percentile is more stable than a single maximum vertex pair.
    distances.sort()
    return distances[min(len(distances) - 1, round((len(distances) - 1) * 0.80))]


def _auto_canal_radius(params: CochleaParams) -> float:
    smallest_planar = min(
        params.cochlear_width_mm,
        params.basal_width_perp_mm or params.cochlear_width_mm * 0.75,
    )
    if params.canal_radius_mm > 0.0:
        return _clamp(params.canal_radius_mm, 0.08, smallest_planar * 0.25)
    # The endocasts represent the scalae/bony labyrinth envelope, not the thin
    # membranous duct. Derive a deliberately substantial shared tube radius
    # from both measured face-on diameters. This equation is identical for all
    # specimens; canal_radius_mm remains an optional explicit user override.
    radius = (
        params.cochlear_width_mm * 0.085
        + (params.basal_width_perp_mm or params.cochlear_width_mm * 0.75) * 0.040
    ) * _clamp(params.canal_thickness_scale, 0.60, 1.80)
    return _clamp(radius, smallest_planar * 0.045, smallest_planar * 0.22)


def _overall_perpendicular_span(params: CochleaParams) -> float:
    """Estimate the face-on envelope while keeping W2 a basal landmark.

    W2 is the shorter diameter of the *basal turn* perpendicular to Cw. It is
    not the Y bounding box of every whorl. Applying W2 directly to the entire
    path made low-W2 specimens (especially Zygorhiza) artificially elliptical.
    Here it is a deliberately soft influence on the overall planform; the
    winding remains predominantly organized by Cw and the measured turn count.
    """

    major_width = params.cochlear_width_mm
    basal_width = params.basal_width_perp_mm or major_width
    measured_aspect = _clamp(basal_width / max(major_width, EPSILON), 0.35, 1.0)
    influence = _clamp(params.w2_planform_influence, 0.0, 1.0)
    softened_aspect = 1.0 - influence * (1.0 - measured_aspect)
    return major_width * _clamp(softened_aspect, 0.78, 1.0)


def _derived_turn_tiering(params: CochleaParams) -> float:
    """Keep one shared tiering model; Ch itself already encodes flatness."""

    return params.turn_tiering


def _derived_canal_height_scale(
    params: CochleaParams,
    canal_radius: float,
) -> float:
    """Return the physical endocast canal-height scale.

    The outer Ch constraint is satisfied by solving centerline rise around this
    physical tube thickness rather than scaling the completed mesh in Z.
    """

    del canal_radius  # Kept in the signature for API compatibility.
    return _clamp(params.canal_height_scale, 0.55, 1.60)


def _candidate_path(
    params: CochleaParams,
    radial_power: float,
    mid_bulge: float,
    canal_radius: float,
    centerline_rise_mm: float,
) -> list[Vector]:
    perpendicular = _overall_perpendicular_span(params)
    x_span = max(params.cochlear_width_mm - canal_radius * 2.0, canal_radius * 2.0)
    y_span = max(perpendicular - canal_radius * 2.0, canal_radius * 2.0)
    # Ch is the external cochlear height, not the centerline's total climb.
    # The enclosing build solver supplies the centerline rise that makes the
    # complete tube envelope match Ch while preserving physical canal height.
    z_span = max(0.0, centerline_rise_mm)
    raw = _raw_spiral(params, radial_power, mid_bulge, params.longitudinal_samples)
    return _scale_path_to_spans(raw, x_span, y_span, z_span, params.handedness)


def _fit_spiral_profile(
    params: CochleaParams,
    canal_radius: float,
    centerline_rise_mm: float,
) -> tuple[list[Vector], float, float, float]:
    target_length = params.cochlear_length_mm
    target_itd = max(
        0.0,
        params.interturn_distance_mm * (1.0 + params.packing_bias * 0.28),
    )
    best: tuple[float, float, float, list[Vector], float] | None = None

    # #T fixes the angular sweep. Cl then solves the shared spiral's radial
    # contraction: low power retains broad inner whorls and a longer path;
    # high power contracts earlier and shortens it. ITD is a secondary
    # landmark because its sampling convention is less stable than Cl/#T/Cw.
    power_prior = 1.0
    bulge_prior = 0.0
    power_center = power_prior
    bulge_center = bulge_prior
    power_half_range = 0.78
    bulge_half_range = 0.32
    for _round in range(5):
        for power_index in range(13):
            power = _clamp(
                power_center
                + power_half_range * (power_index / 6.0 - 1.0),
                0.30,
                2.60,
            )
            for bulge_index in range(13):
                bulge = _clamp(
                    bulge_center
                    + bulge_half_range * (bulge_index / 6.0 - 1.0),
                    -0.42,
                    0.42,
                )
                path = _candidate_path(
                    params, power, bulge, canal_radius, centerline_rise_mm
                )
                length = _path_length(path)
                itd = _estimated_interturn_distance(path, params.turns)
                length_error = abs(length - target_length) / max(
                    target_length, EPSILON
                )
                if target_itd > 0.0:
                    itd_scale = max(target_itd, params.cochlear_width_mm * 0.12)
                    itd_error = abs(itd - target_itd) / itd_scale
                else:
                    itd_error = 0.0
                prior_error = abs(power - power_prior)
                bulge_error = abs(bulge - bulge_prior)
                score = (
                    length_error * 1.00
                    + itd_error * 0.045
                    + prior_error * 0.006
                    + bulge_error * 0.012
                )
                if best is None or score < best[0]:
                    best = (score, power, bulge, path, itd)
        assert best is not None
        _, power_center, bulge_center, _, _ = best
        power_half_range *= 0.34
        bulge_half_range *= 0.34

    assert best is not None
    _, power, bulge, path, itd = best
    return path, power, bulge, itd


def _smoothstep(value: float) -> float:
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _smootherstep(value: float) -> float:
    """C2-continuous blend for anatomical transitions without collar seams."""

    value = _clamp(value, 0.0, 1.0)
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def _basal_inlet_profile(
    base_radius: float,
    fenestra_area_mm2: float,
    enabled: bool,
) -> tuple[float, float, float]:
    """Derive one shared basal flare from FC and canal thickness.

    FC is an anatomical aperture landmark, but it can exceed the cross-section
    of the generated endocast canal. It therefore controls the flare rather
    than being imposed as an impossible literal circular hole. The finished
    mesh is cut to one sharp open boundary after voxel fusion; no lip, bevel,
    collar, inner wall, or recessed cap is added.
    """

    equivalent_fenestra_radius = math.sqrt(
        max(fenestra_area_mm2, 0.0) / math.pi
    )
    if enabled and equivalent_fenestra_radius > 0.0:
        signal = _clamp(
            equivalent_fenestra_radius / max(base_radius * 2.0, EPSILON),
            0.0,
            1.5,
        )
    else:
        signal = 0.0

    basal_flare = 1.0 + 0.18 * signal
    mouth_flare = basal_flare * (1.055 + 0.045 * _clamp(signal, 0.0, 1.0))
    return basal_flare, mouth_flare, equivalent_fenestra_radius


def _cochlear_body_mesh(
    path: Sequence[Vector],
    base_radius: float,
    radial_segments: int,
    apical_taper: float,
    terminal_taper: float,
    terminal_curl: float,
    ridge_strength: float,
    ridge_count: int,
    sulcus_strength: float,
    surface_irregularity: float,
    lamina_extent_pct: float,
    include_lamina: bool,
    fenestra_area_mm2: float,
    include_basal_flare: bool,
    central_fullness: float,
    turn_fusion: float,
    basal_hook: float,
    canal_height_scale: float,
) -> tuple[list[Vector], list[tuple[int, ...]]]:
    """Build one continuous, rounded cochlear body for post-remesh opening.

    The base carries an FC-informed flare, the apex narrows into a rounded tip,
    and the SBL is expressed as a shallow lobe in the same cross section. A
    temporary basal cap only supplies a stable volume for voxel fusion; it is
    removed by a sharp localized cut before export. No visible part is
    assembled from intersecting cylinders, ribbons, collars, or tori.
    """

    tangents, normals, binormals = _parallel_transport_frames(path)
    radial_segments = max(12, radial_segments)
    cap_steps = max(5, radial_segments // 4)
    lamina_fraction = _clamp(lamina_extent_pct / 100.0, 0.0, 1.0)

    basal_flare, mouth_flare, _equivalent_fenestra_radius = _basal_inlet_profile(
        base_radius,
        fenestra_area_mm2,
        include_basal_flare,
    )

    # Each entry is center, normal, binormal, radius, longitudinal t, and
    # whether the ring belongs to the anatomical spiral rather than its cap.
    rings: list[tuple[Vector, Vector, Vector, float, float, bool]] = []
    # Keep the visible lip close to the measured cochlear envelope.  Extending
    # a full-radius tube outward by the throat depth enlarged the raw Cw bounds;
    # the exact planform refit then shrank the anatomical spiral and silently
    # lost several percent of Cl.  The recess belongs *inside* the canal, so the
    # outer lip needs only a short rounding transition.
    base_extension = base_radius * (0.62 + 0.08 * (mouth_flare - 1.0))
    basal_outward = Vector((path[0].x, path[0].y, 0.0))
    if basal_outward.length < 1e-6:
        basal_outward = normals[0].copy()
    else:
        basal_outward.normalize()
    def basal_center(s: float) -> Vector:
        s = _clamp(s, 0.0, 1.0)
        hook_envelope = (1.0 - s) ** 2
        return (
            path[0]
            - tangents[0] * (base_extension * (1.0 - s))
            + basal_outward * (base_radius * basal_hook * 0.82 * hook_envelope)
            + Vector((0.0, 0.0, -base_radius * basal_hook * 0.18 * hook_envelope))
        )

    # Start with a real annular mouth, then settle smoothly into the basal turn.
    # A C2 blend keeps the flare from reading as a separate collar where it
    # joins the measured spiral.
    # The old implementation shrank these rings to a pole, which produced the
    # blunt diamond-shaped cap visible in validation renders.
    for inlet_index in range(cap_steps + 1):
        s = inlet_index / cap_steps
        center = basal_center(s)
        radius = base_radius * (
            mouth_flare
            + (basal_flare - mouth_flare) * _smootherstep(s)
        )
        rings.append((center, normals[0], binormals[0], radius, 0.0, False))

    for index in range(1, len(path)):
        t = index / max(len(path) - 1, 1)
        apical_fraction = _clamp(apical_taper, 0.45, 1.15)
        terminal_fraction = _clamp(
            apical_fraction * _clamp(terminal_taper, 0.35, 1.0),
            0.28,
            apical_fraction,
        )
        # Endocast whorls retain most of their basal cross-section. Taper the
        # full inner turn gently, then reserve the stronger narrowing for only
        # the short helicotrema terminal segment.
        main_taper = 1.0 - (1.0 - apical_fraction) * _smoothstep(t / 0.88)
        apex_neck = 1.0
        if t > 0.90:
            apex_neck = 1.0 - (1.0 - terminal_fraction / apical_fraction) * _smoothstep(
                (t - 0.90) / 0.10
            )
        # Continue that same flare into the basal canal over a broad, C2-smooth
        # interval.  This avoids a visible shoulder at the inlet/spiral join.
        flare_decay = 1.0 + (basal_flare - 1.0) * (
            1.0 - _smootherstep(t / 0.20)
        )
        radius = base_radius * main_taper * apex_neck * flare_decay
        rings.append((path[index], normals[index], binormals[index], radius, t, True))

    # End in a transported half-ellipsoid instead of pinching the final path
    # ring to a cone. A small centripetal bend can continue the local curvature
    # into the cap without adding another measured turn to the centerline.
    terminal_radius = base_radius * terminal_fraction
    cap_curl = _clamp(terminal_curl, 0.0, 0.65)
    apical_inward = _inner_direction(path[-1])
    apical_cap_steps = max(5, radial_segments // 4)
    for cap_index in range(1, apical_cap_steps):
        theta = (math.pi * 0.5) * cap_index / apical_cap_steps
        cap_progress = math.sin(theta)
        center = (
            path[-1]
            + tangents[-1] * (terminal_radius * cap_progress)
            + apical_inward
            * (terminal_radius * cap_curl * cap_progress * cap_progress)
        )
        radius = terminal_radius * math.cos(theta)
        rings.append((center, normals[-1], binormals[-1], radius, 1.0, False))

    vertices: list[Vector] = []
    faces: list[tuple[int, ...]] = []

    mouth_slant = base_radius * (0.14 + 0.04 * _clamp(basal_hook, 0.0, 1.0))
    for ring_index, (center, normal, binormal, radius, t, is_spiral) in enumerate(rings):
        inlet_detail = (
            _smoothstep(ring_index / max(cap_steps, 1))
            if ring_index <= cap_steps
            else 1.0
        )
        # Angular ridges and organic asymmetry are useful along the duct, but
        # they must disappear before the transported terminal cap.  Otherwise
        # even a well-behaved centerline turns them into a star-shaped apex
        # after voxel fusion.  This is one shared anatomical construction rule,
        # independent of specimen identity or turn count.
        basal_detail_ramp = _smootherstep(t / 0.09) if is_spiral else 0.0
        apex_detail_fade = (
            basal_detail_ramp * (1.0 - _smoothstep((t - 0.42) / 0.22))
            if is_spiral
            else 0.0
        )
        along_noise = 1.0 + surface_irregularity * inlet_detail * apex_detail_fade * (
            0.40 * math.sin(t * TAU * 6.0 + 0.4)
            + 0.18 * math.sin(t * TAU * 11.0 + 1.9)
        )
        radius *= along_noise
        inward = _inner_direction(center)
        inner_phi = math.atan2(inward.dot(binormal), inward.dot(normal))
        tangent_index = min(round(t * (len(tangents) - 1)), len(tangents) - 1)
        ring_tangent = tangents[tangent_index]
        up = Vector((0.0, 0.0, 1.0))
        up = up - ring_tangent * up.dot(ring_tangent)
        if up.length < 1e-6:
            up = normal.copy()
        else:
            up.normalize()
        up_phi = math.atan2(up.dot(binormal), up.dot(normal))
        lamina_envelope = 0.0
        if include_lamina and is_spiral and lamina_fraction > 0.0 and t < lamina_fraction:
            # The secondary spiral lamina is an internal shelf, so an endocast
            # should carry only a broad, low-relief trace of it.  A former
            # narrow/high Gaussian read as a radial crack on near-two-turn
            # specimens.  Respect its measured longitudinal extent while
            # fading the external trace before the final whorl.
            lamina_envelope = (0.035 + 0.075 * turn_fusion) * (
                1.0 - _smoothstep(t / lamina_fraction)
            ) * apex_detail_fade
        for radial_index in range(radial_segments):
            phi = TAU * radial_index / radial_segments
            rib = 1.0 + ridge_strength * inlet_detail * apex_detail_fade * math.cos(
                ridge_count * phi + 0.28
            )
            delta = math.atan2(math.sin(phi - inner_phi), math.cos(phi - inner_phi))
            delta_up = math.atan2(math.sin(phi - up_phi), math.cos(phi - up_phi))
            # Keep that low-relief trace axisymmetric on the outer endocast.
            # The actual lamina is internal; a directional external shelf is
            # both anatomically misleading and prone to reading as a crack.
            integrated_lamina = 1.0 + lamina_envelope * 0.35
            # Represent soft turn fusion as a modest, axisymmetric thickening.
            # An older inward-pointing Gaussian produced literal radial webs;
            # voxel remeshing converted their intersections into the triangular
            # apex wrinkles most visible on Orca, Squalodon, and Xiphiacetus.
            # The centerline spacing still determines whether adjacent turns
            # meet, so no artificial directional bridge is needed here.
            apical_web_fade = 1.0 - _smoothstep((t - 0.68) / 0.18)
            fusion_envelope = (
                0.10
                * _clamp(turn_fusion, 0.0, 1.0)
                * math.sin(math.pi * _clamp(t, 0.0, 1.0)) ** 0.72
                * apical_web_fade
            )
            medial_web = 1.0 + fusion_envelope
            # Build apical/modiolar fullness out of the terminal turn itself.
            # This avoids the detached-cone silhouette of an independent core.
            apical_envelope = (
                0.30
                * _clamp(central_fullness, 0.0, 1.0)
                * _smoothstep((t - 0.50) / 0.40)
                * (1.0 - _smoothstep((t - 0.92) / 0.08))
            )
            # Keep the inner whorl full by thickening its own tube uniformly.
            # Pointing any part of this mass toward the axis leaves a radial
            # seam where neighboring surfaces fuse; uniform fullness preserves
            # the volume while keeping the spiral groove and apex smooth.
            apical_mass = 1.0 + apical_envelope
            # A broad superior shoulder breaks the generic round-hose profile.
            # It is strongest through the basal and middle turns, then fades
            # before the helicotrema.
            shoulder_envelope = inlet_detail * (0.065 + 0.055 * turn_fusion) * (
                1.0 - _smoothstep(max(0.0, t - 0.08) / 0.78)
            )
            superior_shoulder = 1.0 + shoulder_envelope * math.exp(
                -(delta_up * delta_up) / (2.0 * 0.48 * 0.48)
            )
            biological_texture = 1.0 + surface_irregularity * inlet_detail * apex_detail_fade * (
                0.34 * math.sin(t * TAU * 15.0 + phi * 2.0)
                + 0.18 * math.sin(t * TAU * 27.0 - phi * 3.0 + 0.8)
            )
            # Add several shallow, longitudinal sulci to the superior surface.
            # Unlike increasing polygon density or adding a shader bump, these
            # are real mesh-level creases that remain legible with transparent
            # and rim-lit materials. Their centers meander gently along the
            # duct, avoiding the machined look of perfectly parallel grooves.
            sulcus_profile = 0.0
            sulcus_wobble = 0.10 * math.sin(t * TAU * 1.35 + 0.45)
            for sulcus_offset, sulcus_width, sulcus_weight in (
                (-0.46, 0.16, 0.70),
                (0.08, 0.12, 1.00),
                (0.56, 0.18, 0.58),
            ):
                sulcus_delta = math.atan2(
                    math.sin(phi - (up_phi + sulcus_offset + sulcus_wobble)),
                    math.cos(phi - (up_phi + sulcus_offset + sulcus_wobble)),
                )
                sulcus_profile += sulcus_weight * math.exp(
                    -(sulcus_delta * sulcus_delta)
                    / (2.0 * sulcus_width * sulcus_width)
                )
            anatomical_sulci = 1.0 - _clamp(sulcus_strength, 0.0, 0.14) * (
                inlet_detail
                * apex_detail_fade
                * min(sulcus_profile, 1.30)
            )
            cross_section_asymmetry = 1.0 + 0.045 * inlet_detail * apex_detail_fade * math.cos(
                phi - inner_phi
            )
            ring_radius = (
                radius
                * rib
                * integrated_lamina
                * medial_web
                * apical_mass
                * superior_shoulder
                * biological_texture
                * anatomical_sulci
                * cross_section_asymmetry
            )
            section_direction = (
                normal * math.cos(phi) + binormal * math.sin(phi)
            ).normalized()
            offset = section_direction * ring_radius
            # Scale canal cross-section height along anatomical Z independently
            # of the overall Ch envelope. Slight longitudinal variation avoids
            # a mechanically uniform hose without changing the mean thickness.
            canal_vertical_scale = _clamp(
                canal_height_scale * (1.0 + 0.025 * math.sin(t * TAU * 1.7 + 0.5)),
                0.55,
                1.60,
            )
            offset.z *= canal_vertical_scale
            point = center + offset
            if ring_index == 0:
                # Tilt the complete rim rather than clipping it with a plane.
                point += tangents[0] * (mouth_slant * math.cos(phi - up_phi))
            vertices.append(point)

    for ring_index in range(len(rings) - 1):
        start = ring_index * radial_segments
        next_start = start + radial_segments
        for radial_index in range(radial_segments):
            next_radial = (radial_index + 1) % radial_segments
            faces.append(
                (
                    start + radial_index,
                    next_start + radial_index,
                    next_start + next_radial,
                    start + next_radial,
                )
            )

    # Temporary volume cap for voxel fusion. The entire cap and the distal
    # flare are removed later, leaving one sharp open boundary ring.
    base_pole_index = len(vertices)
    vertices.append(basal_center(0.0) - tangents[0] * (base_radius * 0.06))
    for radial_index in range(radial_segments):
        next_radial = (radial_index + 1) % radial_segments
        faces.append(
            (
                base_pole_index,
                radial_index,
                next_radial,
            )
        )

    apex_pole_index = len(vertices)
    apex_pole = (
        path[-1]
        + tangents[-1] * terminal_radius
        + apical_inward * (terminal_radius * cap_curl)
    )
    vertices.append(apex_pole)
    last_ring_start = (len(rings) - 1) * radial_segments
    for radial_index in range(radial_segments):
        next_radial = (radial_index + 1) % radial_segments
        faces.append(
            (
                apex_pole_index,
                last_ring_start + next_radial,
                last_ring_start + radial_index,
            )
        )

    return vertices, faces


def _inner_direction(point: Vector, fallback: Vector | None = None) -> Vector:
    direction = Vector((-point.x, -point.y, 0.0))
    if direction.length < 1e-6:
        return fallback.copy() if fallback is not None else Vector((1.0, 0.0, 0.0))
    return direction.normalized()


def _bounds(meshes: dict[str, tuple[list[Vector], list[tuple[int, ...]]]]) -> tuple[Vector, Vector]:
    all_vertices = [vertex for vertices, _faces in meshes.values() for vertex in vertices]
    minimum = Vector(
        (
            min(vertex.x for vertex in all_vertices),
            min(vertex.y for vertex in all_vertices),
            min(vertex.z for vertex in all_vertices),
        )
    )
    maximum = Vector(
        (
            max(vertex.x for vertex in all_vertices),
            max(vertex.y for vertex in all_vertices),
            max(vertex.z for vertex in all_vertices),
        )
    )
    return minimum, maximum


def _fit_geometry_to_planform(
    meshes: dict[str, tuple[list[Vector], list[tuple[int, ...]]]],
    path: Sequence[Vector],
    target: Vector,
) -> tuple[list[Vector], Vector]:
    """Fit Cw and the softened W2 planform without rescaling anatomical Z."""

    minimum, maximum = _bounds(meshes)
    dimensions = maximum - minimum
    center = (minimum + maximum) * 0.5
    scale = Vector(
        (
            target.x / max(dimensions.x, EPSILON),
            target.y / max(dimensions.y, EPSILON),
            1.0,
        )
    )

    def transform(point: Vector) -> Vector:
        delta = point - center
        return Vector((delta.x * scale.x, delta.y * scale.y, delta.z * scale.z))

    for name, (vertices, faces) in list(meshes.items()):
        meshes[name] = ([transform(vertex) for vertex in vertices], faces)
    return [transform(point) for point in path], scale


def _build_geometry_once(
    params: CochleaParams,
    centerline_rise_mm: float,
) -> tuple[
    dict[str, tuple[list[Vector], list[tuple[int, ...]]]],
    list[Vector],
    dict[str, float],
]:
    canal_radius = _auto_canal_radius(params)
    path, radial_power, mid_bulge, itd_before_fit = _fit_spiral_profile(
        params, canal_radius, centerline_rise_mm
    )
    derived_apical_taper = _clamp(params.apical_taper, 0.45, 1.15)
    derived_central_fullness = _clamp(params.central_fullness, 0.0, 1.0)
    derived_turn_fusion = _clamp(params.turn_fusion, 0.0, 1.0)
    derived_canal_height_scale = _derived_canal_height_scale(params, canal_radius)
    published_axial_pitch = params.cochlear_height_mm / max(params.turns, EPSILON)
    meshes: dict[str, tuple[list[Vector], list[tuple[int, ...]]]] = {}
    meshes["Cochlear_Body"] = _cochlear_body_mesh(
        path,
        canal_radius,
        params.radial_segments,
        derived_apical_taper,
        params.terminal_taper,
        params.terminal_curl,
        params.ridge_strength,
        params.ridge_count,
        params.sulcus_strength,
        params.surface_irregularity,
        params.secondary_lamina_extent_pct,
        params.include_secondary_lamina,
        params.fenestra_area_mm2,
        params.include_fenestra_collar,
        derived_central_fullness,
        derived_turn_fusion,
        params.basal_hook,
        derived_canal_height_scale,
    )
    target = Vector(
        (
            params.cochlear_width_mm,
            _overall_perpendicular_span(params),
            params.cochlear_height_mm,
        )
    )
    fitted_path, dimension_scale = _fit_geometry_to_planform(meshes, path, target)
    fitted_centerline_itd = _estimated_interturn_distance(fitted_path, params.turns)
    fitted_base_radius = (
        canal_radius
        * math.sqrt(max(dimension_scale.x * dimension_scale.y, EPSILON))
    )
    fitted_mean_radius = fitted_base_radius * 0.82
    fitted_vertical_radius = (
        canal_radius
        * derived_canal_height_scale
        * max(dimension_scale.z, EPSILON)
    )
    metrics = {
        "radial_power": radial_power,
        "mid_bulge": mid_bulge,
        "canal_radius_before_fit_mm": canal_radius,
        "optimizer_centerline_itd_mm": itd_before_fit,
        "fit_scale_x": dimension_scale.x,
        "fit_scale_y": dimension_scale.y,
        "fit_scale_z": dimension_scale.z,
        "achieved_centerline_length_mm": _path_length(fitted_path),
        "achieved_centerline_interturn_distance_mm": fitted_centerline_itd,
        "achieved_visible_interturn_gap_mm": max(
            0.0, fitted_centerline_itd - fitted_mean_radius * 2.0
        ),
        "base_canal_height_scale": params.canal_height_scale,
        "derived_canal_height_scale": derived_canal_height_scale,
        "published_axial_pitch_mm": published_axial_pitch,
        "derived_apical_taper": derived_apical_taper,
        "terminal_taper": params.terminal_taper,
        "terminal_curl": params.terminal_curl,
        "helicotrema_clearance": params.helicotrema_clearance,
        "derived_central_fullness": derived_central_fullness,
        "derived_turn_fusion": derived_turn_fusion,
        "pitch_to_basal_canal_height_ratio": published_axial_pitch
        / max(fitted_vertical_radius * 2.0, EPSILON),
        "turn_stack_scale": params.turn_stack_scale,
        "vertical_profile": params.vertical_profile,
        "base_turn_tiering": params.turn_tiering,
        "derived_turn_tiering": _derived_turn_tiering(params),
        "achieved_centerline_height_mm": max(point.z for point in fitted_path)
        - min(point.z for point in fitted_path),
        "centerline_height_fraction_of_Ch": (
            max(point.z for point in fitted_path)
            - min(point.z for point in fitted_path)
        )
        / max(params.cochlear_height_mm, EPSILON),
        "estimated_basal_canal_height_mm": fitted_vertical_radius * 2.0,
        "estimated_canal_height_to_width_ratio": fitted_vertical_radius
        / max(fitted_base_radius, EPSILON),
    }
    minimum, maximum = _bounds(meshes)
    metrics["generated_full_envelope_height_before_remesh_mm"] = maximum.z - minimum.z
    metrics["achieved_centerline_pitch_mm"] = (
        metrics["achieved_centerline_height_mm"] / max(params.turns, EPSILON)
    )
    return meshes, fitted_path, metrics


def build_geometry(
    params: CochleaParams,
) -> tuple[
    dict[str, tuple[list[Vector], list[tuple[int, ...]]]],
    list[Vector],
    dict[str, float],
]:
    _validate_params(params)
    target_envelope_height = params.cochlear_height_mm * _clamp(
        params.turn_stack_scale, 0.35, 3.0
    )

    # Solve centerline rise against the complete mesh envelope. Ch is measured
    # across the external cochlea; treating it as centerline rise adds canal
    # thickness twice and creates artificial gaps between successive whorls.
    # Preserve a small nonzero helical rise even when Ch is close to the raw
    # canal diameter. If the requested canal height cannot coexist with the
    # measured envelope, reduce it through this same shared constraint rather
    # than allowing the mesh to exceed Ch or adding a specimen override.
    minimum_centerline_rise = target_envelope_height * 0.10
    solver_params = params
    low_rise = minimum_centerline_rise
    high_rise = max(target_envelope_height, EPSILON)
    low_result = _build_geometry_once(solver_params, low_rise)

    def envelope_height(
        result: tuple[
            dict[str, tuple[list[Vector], list[tuple[int, ...]]]],
            list[Vector],
            dict[str, float],
        ]
    ) -> float:
        return float(result[2]["generated_full_envelope_height_before_remesh_mm"])

    low_height = envelope_height(low_result)
    canal_scale_limited = False
    if low_height > target_envelope_height:
        scale_low = 0.55
        scale_high = _clamp(params.canal_height_scale, 0.55, 1.60)
        scale_candidates: list[
            tuple[
                float,
                CochleaParams,
                tuple[
                    dict[str, tuple[list[Vector], list[tuple[int, ...]]]],
                    list[Vector],
                    dict[str, float],
                ],
            ]
        ] = []
        for _iteration in range(8):
            scale_trial = (scale_low + scale_high) * 0.5
            params_trial = replace(params, canal_height_scale=scale_trial)
            result_trial = _build_geometry_once(
                params_trial, minimum_centerline_rise
            )
            height_trial = envelope_height(result_trial)
            scale_candidates.append((scale_trial, params_trial, result_trial))
            if height_trial > target_envelope_height:
                scale_high = scale_trial
            else:
                scale_low = scale_trial
        _scale, solver_params, low_result = min(
            scale_candidates,
            key=lambda item: abs(
                envelope_height(item[2]) - target_envelope_height
            ),
        )
        low_height = envelope_height(low_result)
        canal_scale_limited = True

    high_result = _build_geometry_once(solver_params, high_rise)
    candidates = [low_result, high_result]
    high_height = envelope_height(high_result)
    for _iteration in range(7):
        if high_height - low_height > EPSILON:
            fraction = _clamp(
                (target_envelope_height - low_height)
                / (high_height - low_height),
                0.08,
                0.92,
            )
        else:
            fraction = 0.5
        trial_rise = low_rise + (high_rise - low_rise) * fraction
        trial_result = _build_geometry_once(solver_params, trial_rise)
        candidates.append(trial_result)
        trial_height = envelope_height(trial_result)
        if trial_height < target_envelope_height:
            low_rise, low_height, low_result = trial_rise, trial_height, trial_result
        else:
            high_rise, high_height, high_result = trial_rise, trial_height, trial_result

    meshes, path, metrics = min(
        candidates,
        key=lambda result: abs(envelope_height(result) - target_envelope_height),
    )

    metrics["target_centerline_length_mm"] = params.cochlear_length_mm
    metrics["centerline_length_error_pct"] = (
        100.0
        * (
            metrics["achieved_centerline_length_mm"] - params.cochlear_length_mm
        )
        / params.cochlear_length_mm
    )
    metrics["target_width_mm"] = params.cochlear_width_mm
    metrics["target_perpendicular_width_mm"] = (
        _overall_perpendicular_span(params)
    )
    metrics["input_basal_width_perp_w2_mm"] = (
        params.basal_width_perp_mm or params.cochlear_width_mm * 0.75
    )
    metrics["w2_planform_influence"] = params.w2_planform_influence
    metrics["target_full_envelope_height_mm"] = target_envelope_height
    metrics["requested_canal_height_scale"] = params.canal_height_scale
    metrics["canal_height_scale_limited_by_Ch"] = canal_scale_limited
    metrics["full_envelope_height_error_mm"] = (
        metrics["generated_full_envelope_height_before_remesh_mm"]
        - target_envelope_height
    )
    metrics["height_measurement_model"] = (
        "Ch is the external cochlear envelope; Ch/#T is a derived morphometric ratio, not centerline pitch"
    )
    metrics["turns"] = params.turns
    metrics["target_angular_sweep_degrees"] = params.turns * 360.0
    metrics["shape_fit_driver"] = (
        "#T angular sweep + Cl contraction + Cw planform + Ch external envelope; "
        "W2/ITD secondary"
    )
    metrics["cochlear_length_used_for_shape"] = True
    return meshes, path, metrics


def _validate_params(params: CochleaParams) -> None:
    positive = {
        "cochlear_length_mm": params.cochlear_length_mm,
        "cochlear_width_mm": params.cochlear_width_mm,
        "cochlear_height_mm": params.cochlear_height_mm,
        "turns": params.turns,
    }
    for name, value in positive.items():
        if value <= 0.0:
            raise ValueError(f"{name} must be greater than zero")
    if params.turns < 1.0 or params.turns > 5.0:
        raise ValueError("turns must be between 1 and 5")
    if params.longitudinal_samples < 64:
        raise ValueError("longitudinal_samples must be at least 64")
    if params.radial_segments < 8:
        raise ValueError("radial_segments must be at least 8")
    if params.normalize_voxel_size and params.voxels_across_cochlear_width < 32:
        raise ValueError("voxels_across_cochlear_width must be at least 32")


def _effective_voxel_size_mm(params: CochleaParams) -> float:
    """Return a shared, scale-normalized voxel grid size.

    A fixed physical voxel size oversamples large cochleae and undersamples
    small ones.  Measuring resolution as voxels across Cw keeps comparable
    silhouettes and polygon density across taxa without specimen tuning.
    """

    if params.normalize_voxel_size:
        requested = params.cochlear_width_mm / max(
            float(params.voxels_across_cochlear_width), 1.0
        )
    else:
        requested = params.voxel_size_mm
    # Voxel remesh connectivity can change at insignificant floating-point
    # differences. Quantizing to 0.005 mm makes regeneration deterministic
    # while remaining far below the intended visible surface resolution.
    quantized = round(float(requested) / 0.005) * 0.005
    return _clamp(quantized, 0.025, 0.50)


def _material(name: str, color: tuple[float, float, float, float], roughness: float) -> bpy.types.Material:
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = roughness
        principled.inputs["Metallic"].default_value = 0.0
        texture_coordinates = material.node_tree.nodes.new("ShaderNodeTexCoord")
        noise = material.node_tree.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 3.2
        noise.inputs["Detail"].default_value = 4.0
        noise.inputs["Roughness"].default_value = 0.68
        bump = material.node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.16
        bump.inputs["Distance"].default_value = 0.07
        material.node_tree.links.new(
            texture_coordinates.outputs["Generated"], noise.inputs["Vector"]
        )
        material.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        material.node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    material.diffuse_color = color
    return material


def _create_mesh_object(
    name: str,
    vertices: Sequence[Vector],
    faces: Sequence[Sequence[int]],
    collection: bpy.types.Collection,
    material: bpy.types.Material,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata([tuple(vertex) for vertex in vertices], [], [tuple(face) for face in faces])
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return obj


def _join_mesh_objects(
    objects: Sequence[bpy.types.Object],
    final_name: str,
) -> bpy.types.Object:
    if not objects:
        raise ValueError("No mesh objects were created")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    result = bpy.context.view_layer.objects.active
    if result is None:
        raise RuntimeError("Blender did not return a joined cochlear mesh")
    result.name = final_name
    result.data.name = f"{final_name}_Mesh"
    return result


def _remove_disconnected_islands(obj: bpy.types.Object) -> tuple[int, int]:
    """Keep the anatomical shell and remove tiny voxel-remesh fragments."""

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    unvisited = set(bm.verts)
    components: list[list[bmesh.types.BMVert]] = []
    while unvisited:
        stack = [unvisited.pop()]
        component: list[bmesh.types.BMVert] = []
        while stack:
            vertex = stack.pop()
            component.append(vertex)
            for edge in vertex.link_edges:
                neighbor = edge.other_vert(vertex)
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    stack.append(neighbor)
        components.append(component)

    removed_islands = max(0, len(components) - 1)
    removed_vertices = 0
    if removed_islands:
        largest = max(components, key=len)
        keep = set(largest)
        remove = [vertex for vertex in bm.verts if vertex not in keep]
        removed_vertices = len(remove)
        bmesh.ops.delete(bm, geom=remove, context="VERTS")
        bm.to_mesh(obj.data)
        obj.data.update()
    bm.free()
    return removed_islands, removed_vertices


def _voxel_fuse_object(
    obj: bpy.types.Object, voxel_size_mm: float
) -> tuple[int, int]:
    """Fuse overlapping anatomical envelopes into one watertight shell."""

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.data.remesh_voxel_size = max(0.025, float(voxel_size_mm))
    bpy.ops.object.voxel_remesh()
    removed = _remove_disconnected_islands(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        obj.data.update()
    bm.free()
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return removed


def _boundary_statistics(obj: bpy.types.Object) -> dict[str, int | bool]:
    """Describe intentional open boundaries separately from topology faults."""

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    wire_edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
    junction_edges = [edge for edge in bm.edges if len(edge.link_faces) > 2]
    adjacency: dict[bmesh.types.BMVert, set[bmesh.types.BMVert]] = {}
    for edge in boundary_edges:
        first, second = edge.verts
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
    unvisited = set(adjacency)
    boundary_components = 0
    closed_loops = 0
    while unvisited:
        boundary_components += 1
        start = unvisited.pop()
        stack = [start]
        component = {start}
        while stack:
            vertex = stack.pop()
            for neighbor in adjacency.get(vertex, set()):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        if component and all(len(adjacency[vertex]) == 2 for vertex in component):
            closed_loops += 1
    result: dict[str, int | bool] = {
        "boundary_edges": len(boundary_edges),
        "boundary_components": boundary_components,
        "closed_boundary_loops": closed_loops,
        "wire_edges": len(wire_edges),
        "junction_edges": len(junction_edges),
        "single_clean_opening": (
            boundary_components == 1
            and closed_loops == 1
            and not wire_edges
            and not junction_edges
        ),
    }
    bm.free()
    return result


def _open_basal_boundary(
    obj: bpy.types.Object,
    cut_point: Vector,
    inward_axis: Vector,
    canal_radius: float,
    voxel_size_mm: float,
) -> dict[str, int | bool]:
    """Remove only the distal basal tip and leave one unbeveled boundary loop.

    The plane is applied to the complete mesh without clearing either side,
    which gives a geometrically clean intersection wherever it crosses. Only
    vertices in the small basal-tube cylinder on the distal side are deleted;
    later whorls cut by the infinite mathematical plane remain untouched and
    manifold. No face is ever created across the resulting boundary.
    """

    axis = inward_axis.normalized()
    up = Vector((0.0, 0.0, 1.0))
    up -= axis * up.dot(axis)
    if up.length < 1e-6:
        up = Vector((0.0, 1.0, 0.0))
        up -= axis * up.dot(axis)
    up.normalize()
    lateral = axis.cross(up).normalized()
    lateral_radius = max(canal_radius * 1.32, voxel_size_mm * 4.0)
    vertical_radius = max(canal_radius * 1.85, voxel_size_mm * 5.0)
    cutter_depth = max(canal_radius * 1.25, voxel_size_mm * 6.0)

    def roi_value(delta: Vector) -> float:
        return (
            (delta.dot(lateral) / max(lateral_radius, EPSILON)) ** 2
            + (delta.dot(up) / max(vertical_radius, EPSILON)) ** 2
        )

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bisect_tolerance = max(1e-5, voxel_size_mm * 0.08)
    cut_faces: list[bmesh.types.BMFace] = []
    cut_edges: set[bmesh.types.BMEdge] = set()
    cut_vertices: set[bmesh.types.BMVert] = set()
    for face in bm.faces:
        signed_values = [
            (vertex.co - cut_point).dot(axis) for vertex in face.verts
        ]
        roi_values = [roi_value(vertex.co - cut_point) for vertex in face.verts]
        if (
            min(signed_values) <= bisect_tolerance
            and max(signed_values) >= -bisect_tolerance
            and min(roi_values) <= 1.05 * 1.05
        ):
            cut_faces.append(face)
            cut_edges.update(face.edges)
            cut_vertices.update(face.verts)
    if not cut_faces:
        bm.free()
        raise RuntimeError("Localized basal cut found no plane-crossing faces")
    bmesh.ops.bisect_plane(
        bm,
        geom=list(cut_vertices) + list(cut_edges) + cut_faces,
        dist=bisect_tolerance,
        plane_co=cut_point,
        plane_no=axis,
        clear_inner=False,
        clear_outer=False,
        use_snap_center=False,
    )
    distal_roi_vertices: set[bmesh.types.BMVert] = set()
    seed_candidates: list[tuple[float, float, bmesh.types.BMVert]] = []
    for vertex in bm.verts:
        delta = vertex.co - cut_point
        signed_distance = delta.dot(axis)
        radial_value = roi_value(delta)
        if (
            -cutter_depth <= signed_distance < -1e-6
            and radial_value <= 1.05 * 1.05
        ):
            distal_roi_vertices.add(vertex)
            if radial_value <= 1.0:
                seed_candidates.append((radial_value, signed_distance, vertex))
    if not seed_candidates:
        bm.free()
        raise RuntimeError("Localized basal cut found no distal vertices")
    seed = min(seed_candidates, key=lambda item: (item[0], item[1]))[2]
    delete_set = {seed}
    stack = [seed]
    while stack:
        vertex = stack.pop()
        for edge in vertex.link_edges:
            neighbor = edge.other_vert(vertex)
            if neighbor in distal_roi_vertices and neighbor not in delete_set:
                delete_set.add(neighbor)
                stack.append(neighbor)
    if len(delete_set) > len(bm.verts) * 0.08:
        delete_fraction = len(delete_set) / max(len(bm.verts), 1)
        bm.free()
        raise RuntimeError(
            "Basal distal component unexpectedly includes "
            f"{delete_fraction:.2%} of the mesh (8% safety limit)"
        )
    bmesh.ops.delete(bm, geom=list(delete_set), context="VERTS")

    # A plane cut through voxel-remeshed geometry can occasionally leave a
    # one-face flap that touches the cochlear shell at only a single vertex.
    # It is not a useful part of the surface and turns the otherwise circular
    # rim into a figure-eight graph (one boundary vertex of degree four).
    # Keep the largest face component when connectivity is measured across
    # shared edges; this removes such point-attached flaps without filling,
    # beveling, or otherwise changing the intended open basal boundary.
    unvisited_faces = set(bm.faces)
    face_components: list[set[bmesh.types.BMFace]] = []
    while unvisited_faces:
        start_face = unvisited_faces.pop()
        component = {start_face}
        stack = [start_face]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for neighbor in edge.link_faces:
                    if neighbor in unvisited_faces:
                        unvisited_faces.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        face_components.append(component)
    removed_face_islands = max(0, len(face_components) - 1)
    removed_face_island_faces = 0
    if removed_face_islands:
        keep_faces = max(face_components, key=len)
        remove_faces = [
            face for component in face_components
            if component is not keep_faces
            for face in component
        ]
        removed_face_island_faces = len(remove_faces)
        bmesh.ops.delete(bm, geom=remove_faces, context="FACES")

    wire_edges = [edge for edge in bm.edges if not edge.link_faces]
    if wire_edges:
        bmesh.ops.delete(bm, geom=wire_edges, context="EDGES")
    isolated_vertices = [vertex for vertex in bm.verts if not vertex.link_edges]
    if isolated_vertices:
        bmesh.ops.delete(bm, geom=isolated_vertices, context="VERTS")
    # Clean voxel stair-stepping without adding a bevel or changing topology.
    # Boundary vertices remain on the cut plane and the surface still ends at
    # a zero-thickness edge suitable for a transparent rim shader.
    for _iteration in range(3):
        boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
        boundary_neighbors: dict[
            bmesh.types.BMVert, list[bmesh.types.BMVert]
        ] = {}
        for edge in boundary_edges:
            first, second = edge.verts
            boundary_neighbors.setdefault(first, []).append(second)
            boundary_neighbors.setdefault(second, []).append(first)
        targets: dict[bmesh.types.BMVert, Vector] = {}
        for vertex, neighbors in boundary_neighbors.items():
            if len(neighbors) != 2:
                continue
            average = (neighbors[0].co + neighbors[1].co) * 0.5
            target = vertex.co.lerp(average, 0.34)
            target -= axis * (target - cut_point).dot(axis)
            targets[vertex] = target
        for vertex, target in targets.items():
            vertex.co = target
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    removed_islands, removed_vertices = _remove_disconnected_islands(obj)
    result = _boundary_statistics(obj)
    result["removed_cut_face_islands"] = removed_face_islands
    result["removed_cut_face_island_faces"] = removed_face_island_faces
    result["removed_cut_islands"] = removed_islands
    result["removed_cut_island_vertices"] = removed_vertices
    return result


def _refit_object_planform(
    obj: bpy.types.Object,
    target: Vector,
) -> Vector:
    """Bake the exact measured outer envelope into the remeshed shell.

    The geometry solver already establishes the morphology.  This final, small
    correction removes voxel-remesh drift so Cw, perpendicular span, and Ch are
    the dimensions of the finished mesh rather than of its pre-remesh input.
    """

    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    if not coordinates:
        raise ValueError("Cannot fit an empty cochlear mesh")
    minimum = Vector(
        (
            min(point.x for point in coordinates),
            min(point.y for point in coordinates),
            min(point.z for point in coordinates),
        )
    )
    maximum = Vector(
        (
            max(point.x for point in coordinates),
            max(point.y for point in coordinates),
            max(point.z for point in coordinates),
        )
    )
    center = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    scale = Vector(
        (
            target.x / max(dimensions.x, EPSILON),
            target.y / max(dimensions.y, EPSILON),
            target.z / max(dimensions.z, EPSILON),
        )
    )
    for vertex in obj.data.vertices:
        delta = vertex.co - center
        vertex.co = Vector(
            (delta.x * scale.x, delta.y * scale.y, delta.z * scale.z)
        )
    obj.data.update()
    return scale


def remove_collection(name: str) -> None:
    collection = bpy.data.collections.get(name)
    if collection is None:
        return
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def generate_cochlea(
    params: CochleaParams,
    parent_collection: bpy.types.Collection | None = None,
    replace_existing: bool = True,
) -> tuple[bpy.types.Collection, dict[str, float]]:
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 0.001

    safe_name = _safe_name(params.species_name)
    collection_name = f"Cochlea_{safe_name}"
    if replace_existing:
        remove_collection(collection_name)
    collection = bpy.data.collections.new(collection_name)
    if parent_collection is None:
        scene.collection.children.link(collection)
    else:
        parent_collection.children.link(collection)

    meshes, path, metrics = build_geometry(params)
    bone_material = _material("Cochlea Bone", (0.86, 0.61, 0.32, 1.0), 0.58)

    created: list[bpy.types.Object] = []
    for part_name, (vertices, faces) in meshes.items():
        created.append(
            _create_mesh_object(
                f"{safe_name}_{part_name}",
                vertices,
                faces,
                collection,
                bone_material,
            )
        )

    cochlea = _join_mesh_objects(created, f"{safe_name}_Cochlea")
    effective_voxel_size_mm = _effective_voxel_size_mm(params)
    if params.use_scan_shell:
        removed_islands, removed_vertices = _voxel_fuse_object(
            cochlea, effective_voxel_size_mm
        )
        fitted_base_radius_before_refit = (
            metrics["canal_radius_before_fit_mm"]
            * math.sqrt(
                max(metrics["fit_scale_x"] * metrics["fit_scale_y"], EPSILON)
            )
        )
        basal_axis = (path[1] - path[0]).normalized()
        basal_cut_point = path[0] - basal_axis * (
            fitted_base_radius_before_refit * 0.50
        )
        boundary_stats = _open_basal_boundary(
            cochlea,
            basal_cut_point,
            basal_axis,
            fitted_base_radius_before_refit,
            effective_voxel_size_mm,
        )
        target = Vector(
            (
                params.cochlear_width_mm,
                _overall_perpendicular_span(params),
                params.cochlear_height_mm,
            )
        )
        post_scale = _refit_object_planform(cochlea, target)
        path = [
            Vector(
                (
                    point.x * post_scale.x,
                    point.y * post_scale.y,
                    point.z * post_scale.z,
                )
            )
            for point in path
        ]
        achieved_length = _path_length(path)
        achieved_centerline_height = max(point.z for point in path) - min(
            point.z for point in path
        )
        centerline_itd = _estimated_interturn_distance(path, params.turns)
        planar_scale = math.sqrt(max(post_scale.x * post_scale.y, EPSILON))
        fitted_base_radius = (
            metrics["canal_radius_before_fit_mm"]
            * math.sqrt(
                max(metrics["fit_scale_x"] * metrics["fit_scale_y"], EPSILON)
            )
            * planar_scale
        )
        fitted_vertical_radius = (
            metrics["canal_radius_before_fit_mm"]
            * metrics["derived_canal_height_scale"]
            * metrics["fit_scale_z"]
            * post_scale.z
        )
        estimated_radius = fitted_base_radius * 0.82
        inner_ratio = metrics["derived_apical_taper"]
        terminal_ratio = _clamp(
            inner_ratio * _clamp(params.terminal_taper, 0.35, 1.0),
            0.28,
            inner_ratio,
        )
        coordinates = [vertex.co for vertex in cochlea.data.vertices]
        full_envelope_height = (
            max(point.z for point in coordinates) - min(point.z for point in coordinates)
        )
        metrics.update(
            {
                "post_remesh_scale_x": post_scale.x,
                "post_remesh_scale_y": post_scale.y,
                "post_remesh_scale_z": post_scale.z,
                "voxel_size_mm": effective_voxel_size_mm,
                "requested_voxel_size_mm": params.voxel_size_mm,
                "voxel_size_normalized": float(params.normalize_voxel_size),
                "voxels_across_cochlear_width": float(
                    params.voxels_across_cochlear_width
                ),
                "removed_voxel_islands": removed_islands,
                "removed_voxel_island_vertices": removed_vertices,
                "basal_opening_boundary_edges": boundary_stats["boundary_edges"],
                "basal_opening_boundary_components": boundary_stats[
                    "boundary_components"
                ],
                "basal_opening_closed_loops": boundary_stats[
                    "closed_boundary_loops"
                ],
                "basal_opening_wire_edges": boundary_stats["wire_edges"],
                "basal_opening_junction_edges": boundary_stats["junction_edges"],
                "removed_basal_cut_islands": boundary_stats[
                    "removed_cut_islands"
                ],
                "removed_basal_cut_island_vertices": boundary_stats[
                    "removed_cut_island_vertices"
                ],
                "basal_opening_single_clean_loop": boundary_stats[
                    "single_clean_opening"
                ],
                "estimated_basal_tube_diameter_mm": fitted_base_radius * 2.0,
                "estimated_basal_canal_height_mm": fitted_vertical_radius * 2.0,
                "estimated_canal_height_to_width_ratio": fitted_vertical_radius
                / max(fitted_base_radius, EPSILON),
                "estimated_inner_turn_diameter_mm": fitted_base_radius
                * 2.0
                * inner_ratio,
                "estimated_terminal_tip_diameter_mm": fitted_base_radius
                * 2.0
                * terminal_ratio,
                "inner_to_basal_thickness_ratio": inner_ratio,
                "terminal_to_basal_thickness_ratio": terminal_ratio,
                "achieved_centerline_length_mm": achieved_length,
                "achieved_centerline_height_mm": achieved_centerline_height,
                "centerline_height_fraction_of_Ch": achieved_centerline_height
                / max(params.cochlear_height_mm, EPSILON),
                "achieved_centerline_pitch_mm": achieved_centerline_height
                / max(params.turns, EPSILON),
                "actual_full_envelope_height_mm": full_envelope_height,
                "actual_full_envelope_height_error_mm": full_envelope_height
                - params.cochlear_height_mm,
                "centerline_length_error_pct": 100.0
                * (achieved_length - params.cochlear_length_mm)
                / params.cochlear_length_mm,
                "achieved_centerline_interturn_distance_mm": centerline_itd,
                "achieved_visible_interturn_gap_mm": max(
                    0.0, centerline_itd - estimated_radius * 2.0
                ),
            }
        )

    collection["generator_version"] = "0.32.1"
    collection["species_name"] = params.species_name
    collection["specimen"] = params.specimen
    collection["parameters_json"] = json.dumps(asdict(params), sort_keys=True)
    collection["metrics_json"] = json.dumps(metrics, sort_keys=True)
    return collection, metrics


class COCHLEA_PG_settings(PropertyGroup):
    preset: EnumProperty(
        name="Preset",
        items=[
            ("AETIOCETUS", "cf. Aetiocetus", "USNM 256597"),
            ("ECHOVENATOR", "Echovenator", "GSM 1098"),
            ("SCAPHOKOGIA", "Scaphokogia", "USNM 452993"),
            ("SEMIROSTRUM", "Semirostrum", "SDNHM 65276"),
            ("SQUALODON", "Squalodon", "USNM 10484"),
            ("ZYGORHIZA", "Zygorhiza", "ALMNH 2000 1.2.1"),
            ("CUSTOM", "Custom", "Use the values below"),
        ],
        default="ECHOVENATOR",
    )
    species_name: StringProperty(name="Species / label", default="Echovenator sandersi")
    specimen: StringProperty(name="Specimen", default="GSM 1098")
    cochlear_length_mm: FloatProperty(
        name="Canal length Cl (mm)", default=34.13, min=1.0
    )
    cochlear_width_mm: FloatProperty(name="Major width Cw (mm)", default=9.05, min=0.5)
    basal_width_perp_mm: FloatProperty(name="Perpendicular width W2 (mm)", default=6.87, min=0.0)
    turns: FloatProperty(name="Turns", default=2.0, min=1.0, max=5.0, precision=2)
    cochlear_height_mm: FloatProperty(name="Height Ch (mm)", default=6.77, min=0.5)
    interturn_distance_mm: FloatProperty(name="Inter-turn distance (mm)", default=1.85, min=0.0)
    secondary_lamina_extent_pct: FloatProperty(name="SBL extent", default=69.75, min=0.0, max=100.0, subtype="PERCENTAGE")
    spiral_ganglion_diameter_mm: FloatProperty(name="Ganglion diameter (mm)", default=0.40, min=0.0)
    fenestra_area_mm2: FloatProperty(name="Fenestra area (mm²)", default=8.92, min=0.0)
    canal_radius_mm: FloatProperty(name="Canal radius override (mm)", default=0.0, min=0.0)
    packing_bias: FloatProperty(name="Packing bias", default=0.0, min=-1.0, max=1.0)
    canal_thickness_scale: FloatProperty(
        name="Endocast tube thickness", default=1.00, min=0.60, max=1.80
    )
    apical_taper: FloatProperty(
        name="Inner-turn thickness", default=0.88, min=0.45, max=1.15
    )
    terminal_taper: FloatProperty(
        name="Terminal tip ratio", default=0.58, min=0.35, max=1.0
    )
    terminal_curl: FloatProperty(
        name="Terminal centripetal curl", default=0.22, min=0.0, max=0.65
    )
    helicotrema_clearance: FloatProperty(
        name="Helicotrema clearance",
        default=0.16,
        min=0.0,
        max=0.32,
        description="Normalized centerline clearance at the apex; avoids a singular zero-radius terminal",
    )
    w2_planform_influence: FloatProperty(
        name="W2 planform influence", default=0.10, min=0.0, max=1.0
    )
    vertical_profile: FloatProperty(name="Vertical rise profile", default=1.00, min=0.55, max=2.5)
    turn_stack_scale: FloatProperty(
        name="Axial turn stacking", default=1.00, min=0.35, max=3.0
    )
    turn_tiering: FloatProperty(
        name="Whorl tiering", default=0.55, min=0.0, max=0.96
    )
    ridge_strength: FloatProperty(name="Surface ridge strength", default=0.090, min=0.0, max=0.22)
    ridge_count: IntProperty(name="Longitudinal ridges", default=4, min=0, max=8)
    sulcus_strength: FloatProperty(
        name="Longitudinal sulcus depth", default=0.065, min=0.0, max=0.14
    )
    surface_irregularity: FloatProperty(name="Organic irregularity", default=0.045, min=0.0, max=0.12)
    central_fullness: FloatProperty(name="Modiolar fullness", default=0.12, min=0.0, max=1.0)
    turn_fusion: FloatProperty(name="Turn fusion", default=0.0, min=0.0, max=1.0)
    basal_hook: FloatProperty(name="Basal hook", default=0.34, min=0.0, max=1.0)
    canal_height_scale: FloatProperty(
        name="Canal cross-section height", default=0.95, min=0.55, max=1.60
    )
    normalize_voxel_size: BoolProperty(
        name="Normalize voxel size to Cw",
        default=True,
        description="Keep comparable surface resolution across differently sized cochleae",
    )
    voxels_across_cochlear_width: IntProperty(
        name="Voxels across Cw", default=90, min=32, max=400
    )
    voxel_size_mm: FloatProperty(
        name="Manual fusion voxel size (mm)", default=0.11, min=0.025, max=0.50, precision=3
    )
    use_scan_shell: BoolProperty(name="Fuse scan-like shell", default=True)
    handedness: EnumProperty(
        name="Handedness",
        items=[("RIGHT", "Right", "Right cochlea"), ("LEFT", "Left", "Left cochlea")],
        default="RIGHT",
    )
    longitudinal_samples: IntProperty(name="Longitudinal samples", default=320, min=64, max=1200)
    radial_segments: IntProperty(name="Radial segments", default=28, min=8, max=96)
    include_secondary_lamina: BoolProperty(name="Secondary spiral lamina", default=True)
    include_fenestra_collar: BoolProperty(name="Fenestra-informed basal flare", default=True)
    replace_existing: BoolProperty(name="Replace same species", default=True)

    def to_params(self) -> CochleaParams:
        return CochleaParams(
            species_name=self.species_name,
            specimen=self.specimen,
            cochlear_length_mm=self.cochlear_length_mm,
            cochlear_width_mm=self.cochlear_width_mm,
            basal_width_perp_mm=self.basal_width_perp_mm,
            turns=self.turns,
            cochlear_height_mm=self.cochlear_height_mm,
            interturn_distance_mm=self.interturn_distance_mm,
            secondary_lamina_extent_pct=self.secondary_lamina_extent_pct,
            spiral_ganglion_diameter_mm=self.spiral_ganglion_diameter_mm,
            fenestra_area_mm2=self.fenestra_area_mm2,
            canal_radius_mm=self.canal_radius_mm,
            packing_bias=self.packing_bias,
            canal_thickness_scale=self.canal_thickness_scale,
            apical_taper=self.apical_taper,
            terminal_taper=self.terminal_taper,
            terminal_curl=self.terminal_curl,
            helicotrema_clearance=self.helicotrema_clearance,
            w2_planform_influence=self.w2_planform_influence,
            vertical_profile=self.vertical_profile,
            turn_stack_scale=self.turn_stack_scale,
            turn_tiering=self.turn_tiering,
            ridge_strength=self.ridge_strength,
            ridge_count=self.ridge_count,
            sulcus_strength=self.sulcus_strength,
            surface_irregularity=self.surface_irregularity,
            central_fullness=self.central_fullness,
            turn_fusion=self.turn_fusion,
            basal_hook=self.basal_hook,
            canal_height_scale=self.canal_height_scale,
            normalize_voxel_size=self.normalize_voxel_size,
            voxels_across_cochlear_width=self.voxels_across_cochlear_width,
            voxel_size_mm=self.voxel_size_mm,
            use_scan_shell=self.use_scan_shell,
            handedness=self.handedness,
            longitudinal_samples=self.longitudinal_samples,
            radial_segments=self.radial_segments,
            include_secondary_lamina=self.include_secondary_lamina,
            include_fenestra_collar=self.include_fenestra_collar,
        )


class COCHLEA_OT_apply_preset(Operator):
    bl_idname = "cochlea.apply_preset"
    bl_label = "Apply Preset"
    bl_description = "Load the selected specimen-specific measurement preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        settings = context.scene.cochlea_settings
        if settings.preset == "CUSTOM":
            return {"FINISHED"}
        for key, value in SHARED_MORPHOLOGY_DEFAULTS.items():
            setattr(settings, key, value)
        preset = BUILTIN_PRESETS[settings.preset]
        for key, value in preset.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        return {"FINISHED"}


class COCHLEA_OT_generate(Operator):
    bl_idname = "cochlea.generate"
    bl_label = "Generate Cochlea"
    bl_description = "Generate a fitted procedural cochlea from the current measurements"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        settings = context.scene.cochlea_settings
        try:
            collection, metrics = generate_cochlea(
                settings.to_params(), replace_existing=settings.replace_existing
            )
        except Exception as exc:
            self.report({"ERROR"}, f"{type(exc).__name__}: {exc}")
            return {"CANCELLED"}
        context.scene["cochlea_last_collection"] = collection.name
        context.scene["cochlea_last_metrics"] = json.dumps(metrics)
        self.report(
            {"INFO"},
            (
                f"Generated {collection.name}; {metrics['turns']:.2f} turns; "
                f"length error {metrics['centerline_length_error_pct']:+.2f}%"
            ),
        )
        return {"FINISHED"}


class COCHLEA_PT_generator(Panel):
    bl_label = "Cochlea Generator"
    bl_idname = "COCHLEA_PT_generator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Cochlea"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        settings = context.scene.cochlea_settings

        preset_box = layout.box()
        preset_box.prop(settings, "preset")
        preset_box.operator("cochlea.apply_preset")

        identity = layout.box()
        identity.label(text="Identity")
        identity.prop(settings, "species_name")
        identity.prop(settings, "specimen")

        core = layout.box()
        core.label(text="Core measurements")
        core.prop(settings, "turns")
        core.prop(settings, "cochlear_width_mm")
        core.prop(settings, "cochlear_height_mm")
        core.prop(settings, "cochlear_length_mm")

        anatomy = layout.box()
        anatomy.label(text="Additional anatomy")
        anatomy.prop(settings, "basal_width_perp_mm")
        anatomy.prop(settings, "interturn_distance_mm")
        anatomy.prop(settings, "secondary_lamina_extent_pct")
        anatomy.prop(settings, "spiral_ganglion_diameter_mm")
        anatomy.prop(settings, "fenestra_area_mm2")
        anatomy.prop(settings, "include_secondary_lamina")
        anatomy.prop(settings, "include_fenestra_collar")

        shape = layout.box()
        shape.label(text="Shared procedural shape policy")
        shape.label(text="#T sets sweep; Cl solves contraction")
        shape.label(text="No specimen-specific morphology tuning")
        shape.prop(settings, "handedness")

        resolution = layout.box()
        resolution.label(text="Resolution")
        resolution.prop(settings, "longitudinal_samples")
        resolution.prop(settings, "radial_segments")
        resolution.prop(settings, "use_scan_shell")
        if settings.use_scan_shell:
            resolution.prop(settings, "normalize_voxel_size")
            if settings.normalize_voxel_size:
                resolution.prop(settings, "voxels_across_cochlear_width")
            else:
                resolution.prop(settings, "voxel_size_mm")

        layout.prop(settings, "replace_existing")
        layout.operator("cochlea.generate", icon="MESH_DATA")

        raw_metrics = context.scene.get("cochlea_last_metrics")
        if raw_metrics:
            metrics = json.loads(raw_metrics)
            report = layout.box()
            report.label(text="Last result")
            report.label(text=f"Turns: {metrics['turns']:.2f} (angular sweep)")
            report.label(
                text=(
                    f"Length fit: {metrics['achieved_centerline_length_mm']:.2f} mm "
                    f"({metrics['centerline_length_error_pct']:+.2f}%)"
                )
            )
            report.label(
                text=f"Estimated gap: {metrics['achieved_visible_interturn_gap_mm']:.2f} mm"
            )


CLASSES = (
    COCHLEA_PG_settings,
    COCHLEA_OT_apply_preset,
    COCHLEA_OT_generate,
    COCHLEA_PT_generator,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cochlea_settings = PointerProperty(type=COCHLEA_PG_settings)


def unregister() -> None:
    if hasattr(bpy.types.Scene, "cochlea_settings"):
        del bpy.types.Scene.cochlea_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

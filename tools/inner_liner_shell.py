"""Add a visualization-only inner liner to an open generated cochlea shell.

The measured outer endocast body is preserved. Only its final decimated basal
boundary loop is regularized before a smaller sweep follows the same
centerline, closes at the apex, and rolls into an outward-projecting rounded
lip. The result is one closed manifold mesh suitable for transparent/rim-
shaded close-up rendering.
"""

from __future__ import annotations

import math
import hashlib
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils import noise as math_noise


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
for directory in (PROJECT_DIR, SCRIPT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from build_turn_noodle_inspection import local_tube_radius  # noqa: E402
from build_turn_section_inspection import final_centerline  # noqa: E402
from cochlea_generator import CochleaParams, _parallel_transport_frames  # noqa: E402


DEFAULT_INNER_RADIUS_RATIO = 0.60
DEFAULT_MAX_CENTERLINE_RINGS = 125
DEFAULT_CAP_RINGS = 8
DEFAULT_LIP_RINGS = 12
DEFAULT_ORGANIC_AMPLITUDE_RATIO = 0.0024


def mesh_topology(obj: bpy.types.Object) -> dict[str, int | bool]:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    result: dict[str, int | bool] = {
        "vertices": len(bm.verts),
        "faces": len(bm.faces),
        "boundary_edges": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "wire_edges": sum(1 for edge in bm.edges if len(edge.link_faces) == 0),
        "junction_edges": sum(1 for edge in bm.edges if len(edge.link_faces) > 2),
    }
    result["closed_manifold"] = (
        result["boundary_edges"] == 0
        and result["wire_edges"] == 0
        and result["junction_edges"] == 0
    )
    bm.free()
    return result


def triangle_count(obj: bpy.types.Object) -> int:
    return sum(max(1, len(polygon.vertices) - 2) for polygon in obj.data.polygons)


def _ordered_boundary_loop(mesh: bpy.types.Mesh) -> list[int]:
    edge_face_counts: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        polygon_vertices = list(polygon.vertices)
        for index, first in enumerate(polygon_vertices):
            second = polygon_vertices[(index + 1) % len(polygon_vertices)]
            edge = tuple(sorted((first, second)))
            edge_face_counts[edge] = edge_face_counts.get(edge, 0) + 1
    boundary_edges = [edge for edge, count in edge_face_counts.items() if count == 1]
    adjacency: dict[int, list[int]] = {}
    for first, second in boundary_edges:
        adjacency.setdefault(first, []).append(second)
        adjacency.setdefault(second, []).append(first)
    if not adjacency or any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise RuntimeError("Expected one simple basal boundary loop")

    start = min(adjacency)
    loop = [start]
    previous = -1
    current = start
    while True:
        candidates = [vertex for vertex in adjacency[current] if vertex != previous]
        if not candidates:
            raise RuntimeError("Basal boundary traversal stopped early")
        nxt = candidates[0]
        if nxt == start:
            break
        if nxt in loop:
            raise RuntimeError("Basal boundary contains a repeated vertex")
        loop.append(nxt)
        previous, current = current, nxt
    if len(loop) != len(adjacency):
        raise RuntimeError("Generated cochlea has more than one open boundary")
    return loop


def _ring_phase_and_direction(
    boundary: list[Vector],
    center: Vector,
    normal: Vector,
    binormal: Vector,
) -> tuple[float, float]:
    angles = [
        math.atan2((point - center).dot(binormal), (point - center).dot(normal))
        for point in boundary
    ]
    signed_steps = []
    for index, angle in enumerate(angles):
        nxt = angles[(index + 1) % len(angles)]
        signed_steps.append((nxt - angle + math.pi) % math.tau - math.pi)
    direction = 1.0 if sum(signed_steps) >= 0.0 else -1.0
    return angles[0], direction


def _smooth_closed_loop(points: list[Vector], iterations: int = 10) -> list[Vector]:
    smoothed = [point.copy() for point in points]
    for _iteration in range(iterations):
        previous = smoothed
        smoothed = []
        for index, point in enumerate(previous):
            neighbor_average = (
                previous[index - 1] + previous[(index + 1) % len(previous)]
            ) * 0.5
            smoothed.append(point.lerp(neighbor_average, 0.48))
    # Laplacian smoothing regularizes the decimated rim but contracts it. Put
    # the loop back on its original center and average radius so the inlet size
    # is preserved while its small saw-tooth deviations disappear.
    original_center = sum(points, Vector()) / len(points)
    smoothed_center = sum(smoothed, Vector()) / len(smoothed)
    original_radius = sum((point - original_center).length for point in points) / len(points)
    smoothed_radius = sum((point - smoothed_center).length for point in smoothed) / len(smoothed)
    scale = original_radius / max(smoothed_radius, 1.0e-9)
    return [original_center + (point - smoothed_center) * scale for point in smoothed]


def _boundary_fade_masks(
    mesh: bpy.types.Mesh,
    boundary_indices: list[int],
    fade_rings: int = 8,
) -> tuple[list[float], list[float]]:
    adjacency: list[list[int]] = [[] for _vertex in mesh.vertices]
    for edge in mesh.edges:
        first, second = edge.vertices
        adjacency[first].append(second)
        adjacency[second].append(first)
    distances = {index: 0 for index in boundary_indices}
    frontier = set(boundary_indices)
    for distance in range(1, fade_rings + 1):
        next_frontier: set[int] = set()
        for index in frontier:
            for neighbor in adjacency[index]:
                if neighbor not in distances:
                    distances[neighbor] = distance
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    macro = [1.0] * len(mesh.vertices)
    detail = [1.0] * len(mesh.vertices)
    for index, distance in distances.items():
        blend = min(1.0, distance / max(fade_rings, 1))
        smooth = blend * blend * (3.0 - 2.0 * blend)
        macro[index] = 0.62 + 0.38 * smooth
        detail[index] = 0.08 + 0.92 * smooth
    return macro, detail


def _standardize(values: list[float]) -> list[float]:
    mean = sum(values) / max(len(values), 1)
    variance = sum((value - mean) ** 2 for value in values) / max(len(values), 1)
    deviation = math.sqrt(max(variance, 1.0e-12))
    return [(value - mean) / deviation for value in values]


def _noise_offsets(params: CochleaParams) -> tuple[Vector, Vector, Vector]:
    identity = (
        f"{params.species_name}|{params.specimen}|{params.cochlear_length_mm:.6f}|"
        f"{params.cochlear_width_mm:.6f}|{params.turns:.6f}"
    ).encode("utf-8")
    digest = hashlib.sha256(identity).digest()
    values = [byte / 255.0 * 19.0 - 9.5 for byte in digest[:9]]
    return (
        Vector(values[0:3]),
        Vector(values[3:6]),
        Vector(values[6:9]),
    )


def _apply_layered_organic_displacement(
    mesh: bpy.types.Mesh,
    params: CochleaParams,
    macro_mask: list[float],
    detail_mask: list[float],
    amplitude_ratio: float,
) -> dict[str, float]:
    """Apply deterministic physical-scale fBm along smooth vertex normals."""

    width = max(float(params.cochlear_width_mm), 1.0e-6)
    offsets = _noise_offsets(params)
    macro_values: list[float] = []
    meso_values: list[float] = []
    micro_values: list[float] = []
    for vertex in mesh.vertices:
        normalized = vertex.co / width
        macro_values.append(
            math_noise.fractal(
                normalized * 3.0 + offsets[0],
                0.92,
                2.0,
                2.0,
                noise_basis="PERLIN_NEW",
            )
        )
        meso_values.append(
            math_noise.fractal(
                normalized * 8.5 + offsets[1],
                0.86,
                2.05,
                2.4,
                noise_basis="PERLIN_NEW",
            )
        )
        micro_values.append(
            math_noise.fractal(
                normalized * 22.0 + offsets[2],
                0.78,
                2.1,
                1.8,
                noise_basis="PERLIN_NEW",
            )
        )
    macro_values = _standardize(macro_values)
    meso_values = _standardize(meso_values)
    micro_values = _standardize(micro_values)
    combined = [
        0.55 * macro_values[index] * macro_mask[index]
        + (
            0.32 * meso_values[index]
            + 0.13 * micro_values[index]
        )
        * detail_mask[index]
        for index in range(len(mesh.vertices))
    ]
    combined = _standardize(combined)
    rms_amplitude = width * amplitude_ratio
    limit = rms_amplitude * 2.45
    displacements = [
        max(-limit, min(limit, value * rms_amplitude)) for value in combined
    ]
    for vertex, displacement in zip(mesh.vertices, displacements):
        vertex.co += vertex.normal * displacement
    mesh.update()
    return {
        "organic_displacement_rms_mm": rms_amplitude,
        "organic_displacement_limit_mm": limit,
        "organic_displacement_min_mm": min(displacements),
        "organic_displacement_max_mm": max(displacements),
        "organic_macro_wavelength_mm": width / 3.0,
        "organic_meso_wavelength_mm": width / 8.5,
        "organic_micro_wavelength_mm": width / 22.0,
    }


def add_inner_liner(
    source: bpy.types.Object,
    params: CochleaParams,
    metrics: dict[str, object],
    *,
    inner_radius_ratio: float = DEFAULT_INNER_RADIUS_RATIO,
    max_centerline_rings: int = DEFAULT_MAX_CENTERLINE_RINGS,
    cap_rings: int = DEFAULT_CAP_RINGS,
    lip_rings: int = DEFAULT_LIP_RINGS,
    mirror_centerline_x: bool = True,
    organic_displacement: bool = False,
    organic_amplitude_ratio: float = DEFAULT_ORGANIC_AMPLITUDE_RATIO,
) -> tuple[bpy.types.Object, dict[str, int | float | bool]]:
    """Return a closed copy with a rounded mouth and centerline inner surface."""

    if not 0.35 <= inner_radius_ratio <= 0.85:
        raise ValueError("inner_radius_ratio must be between 0.35 and 0.85")
    if not 0.0 <= organic_amplitude_ratio <= 0.02:
        raise ValueError("organic_amplitude_ratio must be between 0.0 and 0.02")
    mesh = source.data
    boundary_indices = _ordered_boundary_loop(mesh)
    boundary = [mesh.vertices[index].co.copy() for index in boundary_indices]
    boundary_center = sum(boundary, Vector()) / len(boundary)

    raw_path = final_centerline(params, metrics)
    if mirror_centerline_x:
        raw_path = [Vector((-point.x, point.y, point.z)) for point in raw_path]
    stride = max(1, (len(raw_path) - 1) // max_centerline_rings)
    path = raw_path[::stride]
    if path[-1] != raw_path[-1]:
        path.append(raw_path[-1])

    tangents, normals, binormals = _parallel_transport_frames(path)
    phase, direction = _ring_phase_and_direction(
        boundary, boundary_center, normals[0], binormals[0]
    )
    ring_segments = len(boundary_indices)
    base_radius = float(metrics["estimated_basal_tube_diameter_mm"]) * 0.5
    apical_fraction = float(metrics["inner_to_basal_thickness_ratio"])
    terminal_fraction = float(metrics["terminal_to_basal_thickness_ratio"])

    vertices = [vertex.co.copy() for vertex in mesh.vertices]
    faces = [tuple(polygon.vertices) for polygon in mesh.polygons]
    source_face_count = len(faces)
    source_material_indices = [polygon.material_index for polygon in mesh.polygons]
    source_macro_mask, source_detail_mask = _boundary_fade_masks(
        mesh, boundary_indices
    )
    lip_mask_ranges: list[tuple[int, int, float]] = []
    transition_mask_ranges: list[tuple[int, int, float]] = []

    smoothed_boundary = _smooth_closed_loop(boundary)
    # The delivery exterior is unchanged except for this last open-edge loop.
    # Regularizing it prevents the 25k collapse-decimation from being magnified
    # into radial wrinkles by the new rolled lip.
    for index, point in zip(boundary_indices, smoothed_boundary):
        vertices[index] = point.copy()
    boundary = smoothed_boundary
    inward = path[0] - boundary_center
    if inward.length < 1.0e-7:
        inward = (path[1] - path[0]).normalized()
    else:
        inward.normalize()
    average_outer_radius = (
        sum((point - boundary_center).length for point in boundary) / len(boundary)
    )
    wall_thickness = average_outer_radius * (1.0 - inner_radius_ratio)

    # Roll the existing edge *outward* as a semicircular lip. Both the outer and
    # inner edges meet the original mouth plane, while the middle of the roll
    # projects toward the viewer rather than recessing into the canal.
    previous_indices = boundary_indices
    inner_rim_start = -1
    for lip_index in range(1, lip_rings + 1):
        u = lip_index / lip_rings
        theta = math.pi * u
        radial_scale = (
            (1.0 + inner_radius_ratio) * 0.5
            + (1.0 - inner_radius_ratio) * 0.5 * math.cos(theta)
        )
        axial_offset = -wall_thickness * 0.55 * math.sin(theta)
        ring_start = len(vertices)
        for point in boundary:
            vertices.append(
                boundary_center
                + (point - boundary_center) * radial_scale
                + inward * axial_offset
            )
        lip_mask_ranges.append((ring_start, len(vertices), u))
        current_indices = [ring_start + index for index in range(ring_segments)]
        for index in range(ring_segments):
            nxt = (index + 1) % ring_segments
            faces.append(
                (
                    previous_indices[index],
                    previous_indices[nxt],
                    current_indices[nxt],
                    current_indices[index],
                )
            )
        previous_indices = current_indices
        inner_rim_start = ring_start

    # Blend the actual, sometimes oblique mouth into the regular inner sweep.
    previous_ring = inner_rim_start
    transition_rings = 6
    inner_mouth_center = boundary_center
    rim_radius = (
        sum((point - boundary_center).length for point in smoothed_boundary)
        / len(smoothed_boundary)
        * inner_radius_ratio
    )
    for transition_index in range(1, transition_rings + 1):
        blend = transition_index / transition_rings
        smooth = blend * blend * (3.0 - 2.0 * blend)
        center = inner_mouth_center.lerp(path[0], smooth)
        radius = rim_radius + (base_radius * inner_radius_ratio - rim_radius) * smooth
        ring_start = len(vertices)
        for radial_index in range(ring_segments):
            phi = phase + direction * math.tau * radial_index / ring_segments
            vertices.append(
                center
                + normals[0] * (math.cos(phi) * radius)
                + binormals[0] * (math.sin(phi) * radius)
            )
        transition_mask_ranges.append((ring_start, len(vertices), smooth))
        for radial_index in range(ring_segments):
            nxt = (radial_index + 1) % ring_segments
            faces.append(
                (
                    previous_ring + radial_index,
                    previous_ring + nxt,
                    ring_start + nxt,
                    ring_start + radial_index,
                )
            )
        previous_ring = ring_start

    for path_index in range(1, len(path)):
        progress = params.turns * path_index / max(len(path) - 1, 1)
        radius = local_tube_radius(
            progress,
            params.turns,
            base_radius,
            apical_fraction,
            terminal_fraction,
        ) * inner_radius_ratio
        ring_start = len(vertices)
        for radial_index in range(ring_segments):
            phi = phase + direction * math.tau * radial_index / ring_segments
            vertices.append(
                path[path_index]
                + normals[path_index] * (math.cos(phi) * radius)
                + binormals[path_index] * (math.sin(phi) * radius)
            )
        for radial_index in range(ring_segments):
            nxt = (radial_index + 1) % ring_segments
            faces.append(
                (
                    previous_ring + radial_index,
                    previous_ring + nxt,
                    ring_start + nxt,
                    ring_start + radial_index,
                )
            )
        previous_ring = ring_start

    terminal_radius = local_tube_radius(
        params.turns,
        params.turns,
        base_radius,
        apical_fraction,
        terminal_fraction,
    ) * inner_radius_ratio
    terminal_center = path[-1]
    for cap_index in range(1, cap_rings):
        theta = math.pi * 0.5 * cap_index / cap_rings
        center = terminal_center + tangents[-1] * (terminal_radius * math.sin(theta))
        radius = terminal_radius * math.cos(theta)
        ring_start = len(vertices)
        for radial_index in range(ring_segments):
            phi = phase + direction * math.tau * radial_index / ring_segments
            vertices.append(
                center
                + normals[-1] * (math.cos(phi) * radius)
                + binormals[-1] * (math.sin(phi) * radius)
            )
        for radial_index in range(ring_segments):
            nxt = (radial_index + 1) % ring_segments
            faces.append(
                (
                    previous_ring + radial_index,
                    previous_ring + nxt,
                    ring_start + nxt,
                    ring_start + radial_index,
                )
            )
        previous_ring = ring_start
    apex_pole = len(vertices)
    vertices.append(terminal_center + tangents[-1] * terminal_radius)
    for radial_index in range(ring_segments):
        nxt = (radial_index + 1) % ring_segments
        faces.append((previous_ring + radial_index, previous_ring + nxt, apex_pole))

    result_mesh = bpy.data.meshes.new(f"{source.name}_Hollow_Mesh")
    result_mesh.from_pydata([tuple(vertex) for vertex in vertices], [], faces)
    for material in mesh.materials:
        result_mesh.materials.append(material)
    for index, material_index in enumerate(source_material_indices):
        result_mesh.polygons[index].material_index = material_index
    result_mesh.update(calc_edges=True)

    result = bpy.data.objects.new(f"{source.name}_Hollow", result_mesh)
    source.users_collection[0].objects.link(result)
    result.matrix_world = source.matrix_world.copy()
    result.color = source.color
    for key in source.keys():
        if key != "_RNA_UI":
            result[key] = source[key]
    result["asset_role"] = "cochlea hollow visualization shell"
    result["inner_radius_ratio"] = inner_radius_ratio
    result["outer_body_preserved"] = True
    result["basal_boundary_smoothed"] = True
    result["lip_direction"] = "outward"

    bm = bmesh.new()
    bm.from_mesh(result_mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(result_mesh)
    result_mesh.update()
    bm.free()
    # Closed-shell normal recalculation has two globally consistent solutions.
    # Preserve the already approved outer orientation and, consequently, make
    # the connected liner face inward toward the cavity.
    comparison_count = min(source_face_count, 500)
    orientation_score = sum(
        result_mesh.polygons[index].normal.dot(mesh.polygons[index].normal)
        for index in range(comparison_count)
    )
    if orientation_score < 0.0:
        bm = bmesh.new()
        bm.from_mesh(result_mesh)
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(result_mesh)
        result_mesh.update()
        bm.free()
    for polygon in result_mesh.polygons:
        polygon.use_smooth = True

    organic_stats: dict[str, float] = {}
    if organic_displacement:
        macro_mask = [1.0] * len(result_mesh.vertices)
        detail_mask = [1.0] * len(result_mesh.vertices)
        macro_mask[: len(source_macro_mask)] = source_macro_mask
        detail_mask[: len(source_detail_mask)] = source_detail_mask
        for start, end, blend in lip_mask_ranges:
            macro_value = 0.62 + 0.10 * blend
            detail_value = 0.08 + 0.10 * blend
            for index in range(start, end):
                macro_mask[index] = macro_value
                detail_mask[index] = detail_value
        for start, end, blend in transition_mask_ranges:
            macro_value = 0.72 + 0.28 * blend
            detail_value = 0.18 + 0.82 * blend
            for index in range(start, end):
                macro_mask[index] = macro_value
                detail_mask[index] = detail_value
        organic_stats = _apply_layered_organic_displacement(
            result_mesh,
            params,
            macro_mask,
            detail_mask,
            organic_amplitude_ratio,
        )
        result["organic_displacement"] = True
        result["organic_displacement_algorithm"] = "three-scale deterministic fBm"
        result["organic_displacement_amplitude_ratio_Cw"] = organic_amplitude_ratio

    topology = mesh_topology(result)
    stats: dict[str, int | float | bool] = {
        **topology,
        "triangles": triangle_count(result),
        "outer_faces_preserved": source_face_count,
        "basal_boundary_vertices": ring_segments,
        "centerline_rings": len(path),
        "inner_radius_ratio": inner_radius_ratio,
        "basal_boundary_smoothed": True,
        "lip_direction_outward": True,
        "organic_displacement": organic_displacement,
        **organic_stats,
    }
    if not topology["closed_manifold"]:
        raise RuntimeError(f"{source.name}: inner-lined result is not closed manifold")
    return result, stats

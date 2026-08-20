"""Add a color-coded turn-count noodle without segmenting cochlear meshes.

The noodle follows the exact deterministic spiral centerline and begins where
the measured spiral begins. The unmeasured inlet flare is deliberately
excluded. Its diameter equals 30% of the local cochlear-tube diameter. It is
one continuous mesh with material transitions at 1.0 and 2.0 turns.
Generated cochlear meshes remain untouched and unsegmented; source/reference
transforms are preserved. For interchange formats that flatten face-material
    assignments, ``split_noodle_by_material`` can emit one coincident mesh object
    per populated turn range without changing the centerline geometry.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
for directory in (PROJECT_DIR, SCRIPT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cochlea_generator import (  # noqa: E402
    CochleaParams,
    _parallel_transport_frames,
    _smoothstep,
)
from build_turn_section_inspection import (  # noqa: E402
    final_centerline,
    hide_reference_overlays,
)


NOODLE_DIAMETER_RATIO = 0.30
NOODLE_RADIAL_SEGMENTS = 14
NOODLE_COLORS = (
    (0.560, 0.120, 1.000, 1.0),
    (1.000, 0.420, 0.020, 1.0),
    (0.000, 0.820, 0.500, 1.0),
)
NOODLE_SECTION_SPECS = (
    {
        "key": "T00_100",
        "label": "0.0-1.0 turns",
        "start": 0.0,
        "end": 1.0,
        "color": NOODLE_COLORS[0],
    },
    {
        "key": "T100_200",
        "label": "1.0-2.0 turns",
        "start": 1.0,
        "end": 2.0,
        "color": NOODLE_COLORS[1],
    },
    {
        "key": "T200_PLUS",
        "label": "2.0+ turns",
        "start": 2.0,
        "end": None,
        "color": NOODLE_COLORS[2],
    },
)


def noodle_section_index(turn_progress: float) -> int:
    if turn_progress < 1.0:
        return 0
    if turn_progress < 2.0:
        return 1
    return 2


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_generator_v24_manual_alignment.blend",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_generator_v24_turn_noodles.blend",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_DIR / "output/turn_noodle_report_v24.json",
    )
    parser.add_argument(
        "--render",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_turn_noodles_v24.png",
    )
    return parser.parse_args(raw)


def remove_existing_noodles() -> None:
    for collection in list(bpy.data.collections):
        if not collection.name.startswith("TURN_NOODLE_"):
            continue
        for obj in list(collection.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)


def noodle_material(spec: dict[str, object]) -> bpy.types.Material:
    name = f"TURN NOODLE | {spec['label']}"
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = spec["color"]
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is not None:
            principled.inputs["Base Color"].default_value = spec["color"]
            principled.inputs["Roughness"].default_value = 0.34
            if "Emission Color" in principled.inputs:
                principled.inputs["Emission Color"].default_value = spec["color"]
            if "Emission Strength" in principled.inputs:
                principled.inputs["Emission Strength"].default_value = 0.62
    return material


def basal_boundary_center(source: bpy.types.Object) -> Vector:
    counts: dict[tuple[int, int], int] = {}
    for polygon in source.data.polygons:
        vertices = list(polygon.vertices)
        for index, start in enumerate(vertices):
            end = vertices[(index + 1) % len(vertices)]
            key = (min(start, end), max(start, end))
            counts[key] = counts.get(key, 0) + 1
    boundary_vertices = {
        vertex
        for edge, count in counts.items()
        if count == 1
        for vertex in edge
    }
    if not boundary_vertices:
        raise RuntimeError(f"Generated mesh {source.name} has no open basal boundary")
    return sum(
        (source.data.vertices[index].co for index in boundary_vertices),
        Vector(),
    ) / len(boundary_vertices)


def extended_centerline(
    _source: bpy.types.Object,
    path: list[Vector],
    turns: float,
) -> tuple[list[Vector], list[float]]:
    # The basal flare lies outside the measured angular sweep. Keep the noodle
    # on the anatomical spiral rather than extending it to the open mesh rim.
    progress = [turns * index / max(len(path) - 1, 1) for index in range(len(path))]
    return path, progress


def local_tube_radius(
    progress: float,
    total_turns: float,
    base_radius: float,
    apical_fraction: float,
    terminal_fraction: float,
) -> float:
    t = progress / max(total_turns, 1.0e-9)
    apical_fraction = max(0.45, min(1.15, apical_fraction))
    terminal_fraction = max(0.28, min(apical_fraction, terminal_fraction))
    main_taper = 1.0 - (1.0 - apical_fraction) * _smoothstep(t / 0.88)
    apex_neck = 1.0
    if t > 0.90:
        apex_neck = 1.0 - (
            1.0 - terminal_fraction / max(apical_fraction, 1.0e-9)
        ) * _smoothstep((t - 0.90) / 0.10)
    return base_radius * main_taper * apex_neck


def create_noodle(
    source: bpy.types.Object,
    collection: bpy.types.Collection,
    name: str,
    path: list[Vector],
    progress: list[float],
    params: CochleaParams,
    metrics: dict[str, object],
    materials: list[bpy.types.Material],
) -> tuple[bpy.types.Object, dict[str, object]]:
    tangents, normals, binormals = _parallel_transport_frames(path)
    base_tube_radius = float(metrics["estimated_basal_tube_diameter_mm"]) * 0.5
    apical_fraction = float(metrics["inner_to_basal_thickness_ratio"])
    terminal_fraction = float(metrics["terminal_to_basal_thickness_ratio"])
    vertices: list[Vector] = []

    noodle_radii: list[float] = []
    for ring_index, center in enumerate(path):
        cochlear_radius = local_tube_radius(
            progress[ring_index],
            params.turns,
            base_tube_radius,
            apical_fraction,
            terminal_fraction,
        )
        noodle_radius = cochlear_radius * NOODLE_DIAMETER_RATIO
        noodle_radii.append(noodle_radius)
        normal = normals[ring_index]
        binormal = binormals[ring_index]
        for radial_index in range(NOODLE_RADIAL_SEGMENTS):
            angle = math.tau * radial_index / NOODLE_RADIAL_SEGMENTS
            vertices.append(
                center
                + normal * (math.cos(angle) * noodle_radius)
                + binormal * (math.sin(angle) * noodle_radius)
            )

    faces: list[tuple[int, ...]] = []
    material_indices: list[int] = []
    for ring_index in range(len(path) - 1):
        first = ring_index * NOODLE_RADIAL_SEGMENTS
        second = first + NOODLE_RADIAL_SEGMENTS
        midpoint_progress = 0.5 * (progress[ring_index] + progress[ring_index + 1])
        classification_progress = min(
            midpoint_progress, max(0.0, params.turns - 1.0e-9)
        )
        material_index = noodle_section_index(classification_progress)
        for radial_index in range(NOODLE_RADIAL_SEGMENTS):
            next_radial = (radial_index + 1) % NOODLE_RADIAL_SEGMENTS
            faces.append(
                (
                    first + radial_index,
                    second + radial_index,
                    second + next_radial,
                    first + next_radial,
                )
            )
            material_indices.append(material_index)

    start_center = len(vertices)
    vertices.append(path[0])
    for radial_index in range(NOODLE_RADIAL_SEGMENTS):
        next_radial = (radial_index + 1) % NOODLE_RADIAL_SEGMENTS
        faces.append((start_center, next_radial, radial_index))
        material_indices.append(0)

    end_center = len(vertices)
    vertices.append(path[-1])
    end_start = (len(path) - 1) * NOODLE_RADIAL_SEGMENTS
    terminal_section = noodle_section_index(max(0.0, params.turns - 1.0e-9))
    for radial_index in range(NOODLE_RADIAL_SEGMENTS):
        next_radial = (radial_index + 1) % NOODLE_RADIAL_SEGMENTS
        faces.append(
            (end_center, end_start + radial_index, end_start + next_radial)
        )
        material_indices.append(terminal_section)

    # The former 2+ marker sphere made the centerline look longer and bulbous.
    # The ordinary closed tube end above is sufficient and adds no marker ball.
    terminal_cap_added = False

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    for material in materials:
        mesh.materials.append(material)
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index
        polygon.use_smooth = True
    mesh.update()

    noodle = bpy.data.objects.new(name, mesh)
    collection.objects.link(noodle)
    noodle.matrix_world = source.matrix_world.copy()
    noodle.show_in_front = True
    noodle["purpose"] = "turn-count centerline noodle"
    noodle["turn_count_origin"] = "anatomical spiral origin; inlet flare excluded"
    noodle["turn_boundaries"] = "1.0, 2.0"
    noodle["diameter_ratio_to_local_cochlear_tube"] = NOODLE_DIAMETER_RATIO
    noodle["terminal_cap_added"] = terminal_cap_added
    noodle["terminal_cap_diameter_ratio_to_noodle"] = 0.0
    noodle["total_turns"] = params.turns
    return noodle, {
        "object": noodle.name,
        "path_points": len(path),
        "diameter_ratio": NOODLE_DIAMETER_RATIO,
        "basal_noodle_diameter_mm": noodle_radii[0] * 2.0,
        "apical_noodle_diameter_mm": noodle_radii[-1] * 2.0,
        "terminal_cap_added": terminal_cap_added,
        "terminal_cap_diameter_mm": 0.0,
        "spiral_origin_local": list(path[0]),
        "inlet_flare_excluded": True,
    }


def split_noodle_by_material(
    noodle: bpy.types.Object,
    collection: bpy.types.Collection | None = None,
) -> list[bpy.types.Object]:
    """Return one single-material mesh object per populated turn section.

    The source noodle is left intact. Adjacent objects reuse the exact boundary
    coordinates, so the visible path remains continuous while GLB importers can
    no longer collapse all three sections to one material.
    """

    if noodle.type != "MESH":
        raise TypeError(f"{noodle.name}: expected a mesh noodle")
    if collection is None:
        if not noodle.users_collection:
            raise RuntimeError(f"{noodle.name}: noodle is not linked to a collection")
        collection = noodle.users_collection[0]

    mesh = noodle.data
    segments: list[bpy.types.Object] = []
    legacy_four_sections = (
        len(mesh.materials) >= 4
        or any(polygon.material_index >= 3 for polygon in mesh.polygons)
    )
    source_material_groups = (
        ((0,), (1, 2), (3,))
        if legacy_four_sections
        else ((0,), (1,), (2,))
    )
    for segment_index, spec in enumerate(NOODLE_SECTION_SPECS):
        source_material_indices = source_material_groups[segment_index]
        polygons = [
            polygon
            for polygon in mesh.polygons
            if polygon.material_index in source_material_indices
        ]
        if not polygons:
            continue

        used_indices = sorted(
            {vertex_index for polygon in polygons for vertex_index in polygon.vertices}
        )
        remap = {old: new for new, old in enumerate(used_indices)}
        vertices = [mesh.vertices[index].co.copy() for index in used_indices]
        faces = [tuple(remap[index] for index in polygon.vertices) for polygon in polygons]

        segment_mesh = bpy.data.meshes.new(
            f"{noodle.name} | {spec['key']}_Mesh"
        )
        segment_mesh.from_pydata(vertices, [], faces)
        segment_mesh.materials.append(noodle_material(spec))
        for polygon in segment_mesh.polygons:
            polygon.material_index = 0
            polygon.use_smooth = True
        segment_mesh.update()

        segment = bpy.data.objects.new(
            f"{noodle.name} | {spec['key']}", segment_mesh
        )
        collection.objects.link(segment)
        segment.matrix_world = noodle.matrix_world.copy()
        segment.show_in_front = noodle.show_in_front
        segment.hide_render = noodle.hide_render
        segment.hide_viewport = noodle.hide_viewport
        segment.hide_set(noodle.hide_get())
        for key in noodle.keys():
            segment[key] = noodle[key]
        segment["turn_section_key"] = str(spec["key"])
        segment["turn_section_label"] = str(spec["label"])
        segment["turn_section_start"] = float(spec["start"])
        segment["turn_section_end"] = (
            -1.0 if spec["end"] is None else float(spec["end"])
        )
        segment["segmented_noodle_mesh"] = True
        segments.append(segment)

    if len(segments) < 2:
        raise RuntimeError(
            f"{noodle.name}: expected at least two populated turn sections; "
            f"found {len(segments)}"
        )
    return segments


def render_workbench(render_path: Path) -> bool:
    scene = bpy.context.scene
    if scene.camera is None:
        return False
    original_engine = scene.render.engine
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(render_path)
    bpy.ops.render.render(write_still=True)
    scene.render.engine = original_engine
    return True


def main() -> None:
    args = parse_args()
    args.input = args.input.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.report = args.report.expanduser().resolve()
    args.render = args.render.expanduser().resolve()
    for path in (args.output.parent, args.report.parent, args.render.parent):
        path.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    remove_existing_noodles()
    hide_reference_overlays()
    root = bpy.data.collections.get("Cochlea_Segmented_Overlay_QA")
    if root is None:
        root = bpy.context.scene.collection

    materials = [noodle_material(spec) for spec in NOODLE_SECTION_SPECS]
    records: list[dict[str, object]] = []
    generated_collections = sorted(
        (
            collection
            for collection in bpy.data.collections
            if collection.name.startswith("02_")
            and collection.name.endswith("_Generated_RIGHT")
        ),
        key=lambda collection: collection.name,
    )

    for generated in generated_collections:
        generated_meshes = [obj for obj in generated.all_objects if obj.type == "MESH"]
        if len(generated_meshes) != 1:
            raise RuntimeError(
                f"Expected one unsegmented generated mesh in {generated.name}; "
                f"found {len(generated_meshes)}"
            )
        source = generated_meshes[0]
        source.hide_set(False)
        source.hide_render = False
        params = CochleaParams.from_mapping(json.loads(generated["parameters_json"]))
        metrics = json.loads(generated["metrics_json"])
        path = final_centerline(params, metrics)
        path, progress = extended_centerline(source, path, params.turns)

        key = generated.name.removeprefix("02_").removesuffix("_Generated_RIGHT")
        collection = bpy.data.collections.new(f"TURN_NOODLE_{key}")
        root.children.link(collection)
        collection["species_name"] = params.species_name
        collection["specimen"] = params.specimen
        collection["total_turns"] = params.turns
        collection["turn_boundaries"] = "1.0, 2.0"
        collection["noodle_diameter_ratio"] = NOODLE_DIAMETER_RATIO
        noodle, noodle_record = create_noodle(
            source,
            collection,
            f"{key} | TURN COUNT NOODLE",
            path,
            progress,
            params,
            metrics,
            materials,
        )
        records.append(
            {
                "key": key,
                "species_name": params.species_name,
                "specimen": params.specimen,
                "total_turns": params.turns,
                "cochlea_object": source.name,
                "cochlea_face_count": len(source.data.polygons),
                "cochlea_unsegmented": True,
                "noodle": noodle_record,
            }
        )

    legend = {
        spec["label"]: {
            "start": spec["start"],
            "end": spec["end"],
            "rgba": list(spec["color"]),
        }
        for spec in NOODLE_SECTION_SPECS
    }
    bpy.context.scene["turn_noodle_legend_json"] = json.dumps(legend, sort_keys=True)
    bpy.context.scene["turn_noodle_note"] = (
        "Generated cochlear meshes are intact and unsegmented. Noodles are continuous "
        "30%-diameter centerline meshes, shown in front in the viewport. Reference "
        "collections remain embedded with transforms unchanged and start hidden."
    )

    report = {
        "source_blend": str(args.input),
        "output_blend": str(args.output),
        "method": "exact procedural spiral centerline; inlet flare excluded",
        "turn_count_origin": "anatomical spiral origin",
        "boundaries_turns": [1.0, 2.0],
        "noodle_diameter_ratio_to_local_cochlear_tube": NOODLE_DIAMETER_RATIO,
        "legend": legend,
        "records": records,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bpy.context.scene["turn_noodle_report"] = str(args.report)
    rendered = render_workbench(args.render)
    bpy.context.scene["turn_noodle_render"] = str(args.render) if rendered else ""
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))


if __name__ == "__main__":
    main()

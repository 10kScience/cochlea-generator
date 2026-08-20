"""Split generated v24 cochleae into color-coded angular-turn sections.

This is a non-destructive inspection aid.  It opens the manual-alignment file,
keeps the source meshes and their user-authored transforms intact, hides each
unsegmented generated master, and creates selectable surface sections for:

    0.0-1.0 turns, 1.0-1.5 turns, 1.5-2.0 turns, and 2.0+ turns.

Turn progress is measured from the basal opening along the exact procedural
centerline.  Surface faces are assigned to the closest sampled centerline
point, so the section boundaries follow the winding even after voxel fusion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from cochlea_generator import CochleaParams, build_geometry  # noqa: E402


SECTION_SPECS = (
    {
        "key": "T00_100",
        "label": "0.0-1.0 turns (basal turn)",
        "start": 0.0,
        "end": 1.0,
        "color": (0.835, 0.235, 0.110, 1.0),
    },
    {
        "key": "T100_150",
        "label": "1.0-1.5 turns",
        "start": 1.0,
        "end": 1.5,
        "color": (0.945, 0.620, 0.055, 1.0),
    },
    {
        "key": "T150_200",
        "label": "1.5-2.0 turns",
        "start": 1.5,
        "end": 2.0,
        "color": (0.000, 0.620, 0.480, 1.0),
    },
    {
        "key": "T200_PLUS",
        "label": "2.0+ turns (apical remainder)",
        "start": 2.0,
        "end": None,
        "color": (0.360, 0.270, 0.790, 1.0),
    },
)


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
        default=PROJECT_DIR / "output/cochlea_generator_v24_turn_sections.blend",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_DIR / "output/turn_section_report_v24.json",
    )
    parser.add_argument(
        "--render",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_turn_sections_v24.png",
    )
    return parser.parse_args(raw)


def section_material(spec: dict[str, object]) -> bpy.types.Material:
    name = f"TURN SECTION | {spec['label']}"
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = spec["color"]
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is not None:
            principled.inputs["Base Color"].default_value = spec["color"]
            principled.inputs["Roughness"].default_value = 0.44
            principled.inputs["Metallic"].default_value = 0.0
            if "Emission Color" in principled.inputs:
                principled.inputs["Emission Color"].default_value = spec["color"]
            if "Emission Strength" in principled.inputs:
                principled.inputs["Emission Strength"].default_value = 0.42
    return material


def section_index(turn_progress: float) -> int:
    # Exact landmark samples belong to the section beginning at that landmark.
    if turn_progress < 1.0:
        return 0
    if turn_progress < 1.5:
        return 1
    if turn_progress < 2.0:
        return 2
    return 3


def final_centerline(
    params: CochleaParams,
    stored_metrics: dict[str, object],
) -> list[Vector]:
    """Rebuild the deterministic v24 path and apply its post-voxel refit."""

    _meshes, path, _rebuilt_metrics = build_geometry(params)
    scale = Vector(
        (
            float(stored_metrics.get("post_remesh_scale_x", 1.0)),
            float(stored_metrics.get("post_remesh_scale_y", 1.0)),
            float(stored_metrics.get("post_remesh_scale_z", 1.0)),
        )
    )
    return [
        Vector((point.x * scale.x, point.y * scale.y, point.z * scale.z))
        for point in path
    ]


def classify_faces(
    source: bpy.types.Object,
    path: list[Vector],
    turns: float,
) -> tuple[list[list[int]], list[float]]:
    tree = KDTree(len(path))
    for index, point in enumerate(path):
        tree.insert(point, index)
    tree.balance()

    assignments: list[list[int]] = [[] for _spec in SECTION_SPECS]
    turn_progresses: list[float] = []
    path_denominator = max(len(path) - 1, 1)
    for polygon in source.data.polygons:
        center = sum(
            (source.data.vertices[index].co for index in polygon.vertices),
            Vector(),
        ) / max(len(polygon.vertices), 1)
        _nearest, path_index, _distance = tree.find(center)
        turn_progress = turns * path_index / path_denominator
        # The terminal centerline sample is part of the final measured turn,
        # not a zero-length new section.  This matters for exact 2.0-turn
        # specimens such as Echovenator.
        classification_progress = min(turn_progress, max(0.0, turns - 1.0e-9))
        assignments[section_index(classification_progress)].append(polygon.index)
        turn_progresses.append(turn_progress)
    return assignments, turn_progresses


def section_object(
    source: bpy.types.Object,
    face_indices: list[int],
    collection: bpy.types.Collection,
    name: str,
    material: bpy.types.Material,
) -> bpy.types.Object:
    used_vertices = sorted(
        {
            vertex_index
            for face_index in face_indices
            for vertex_index in source.data.polygons[face_index].vertices
        }
    )
    remap = {old: new for new, old in enumerate(used_vertices)}
    vertices = [source.data.vertices[index].co.copy() for index in used_vertices]
    faces = [
        tuple(remap[index] for index in source.data.polygons[face_index].vertices)
        for face_index in face_indices
    ]

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.matrix_world = source.matrix_world.copy()
    obj.color = material.diffuse_color
    obj.show_name = False
    return obj


def remove_existing_turn_sections() -> None:
    for collection in list(bpy.data.collections):
        if collection.name.startswith("TURN_SECTIONS_"):
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(collection)


def hide_reference_overlays() -> None:
    """Keep sources in the file but default to an uncluttered turn view."""

    for collection in bpy.data.collections:
        if collection.name.startswith("00_") and collection.name.endswith(
            "_Full_Reference"
        ):
            collection.hide_viewport = True
            collection.hide_render = True
        elif collection.name.startswith("01_") and collection.name.endswith(
            "_Cochlea_Segment"
        ):
            collection.hide_viewport = True
            collection.hide_render = True


def render_if_possible(render_path: Path) -> bool:
    scene = bpy.context.scene
    if scene.camera is None:
        return False
    render_path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(render_path)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
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
    remove_existing_turn_sections()
    hide_reference_overlays()
    root = bpy.data.collections.get("Cochlea_Segmented_Overlay_QA")
    if root is None:
        root = bpy.context.scene.collection

    materials = [section_material(spec) for spec in SECTION_SPECS]
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
        source_objects = [obj for obj in generated.all_objects if obj.type == "MESH"]
        if len(source_objects) != 1:
            raise RuntimeError(
                f"Expected one generated mesh in {generated.name}; found {len(source_objects)}"
            )
        source = source_objects[0]
        params = CochleaParams.from_mapping(json.loads(generated["parameters_json"]))
        metrics = json.loads(generated["metrics_json"])
        path = final_centerline(params, metrics)
        assignments, progress = classify_faces(source, path, params.turns)

        key = generated.name.removeprefix("02_").removesuffix("_Generated_RIGHT")
        sections = bpy.data.collections.new(f"TURN_SECTIONS_{key}")
        root.children.link(sections)
        sections["species_name"] = params.species_name
        sections["specimen"] = params.specimen
        sections["total_turns"] = params.turns
        sections["counting_origin"] = "basal opening"
        sections["section_boundaries_turns"] = "1.0, 1.5, 2.0"
        sections["classification"] = "nearest exact procedural centerline sample"

        section_records: list[dict[str, object]] = []
        for index, (spec, face_indices, material) in enumerate(
            zip(SECTION_SPECS, assignments, materials)
        ):
            if not face_indices:
                continue
            obj = section_object(
                source,
                face_indices,
                sections,
                f"{key} | {spec['label']}",
                material,
            )
            obj["turn_section_index"] = index
            obj["turn_start"] = float(spec["start"])
            obj["turn_end"] = (
                params.turns if spec["end"] is None else min(float(spec["end"]), params.turns)
            )
            obj["total_specimen_turns"] = params.turns
            obj["counting_origin"] = "basal opening"
            section_records.append(
                {
                    "name": obj.name,
                    "label": spec["label"],
                    "start_turn": obj["turn_start"],
                    "end_turn": obj["turn_end"],
                    "face_count": len(face_indices),
                }
            )

        source.name = f"{key} | UNSEGMENTED_GENERATED_MASTER"
        source.hide_set(True)
        source.hide_render = True
        source["turn_section_master"] = True
        records.append(
            {
                "key": key,
                "species_name": params.species_name,
                "specimen": params.specimen,
                "total_turns": params.turns,
                "source_face_count": len(source.data.polygons),
                "section_face_count": sum(len(faces) for faces in assignments),
                "turn_progress_min": min(progress),
                "turn_progress_max": max(progress),
                "sections": section_records,
            }
        )

    legend = {
        spec["label"]: {
            "start": spec["start"],
            "end": spec["end"],
            "rgba": list(spec["color"]),
        }
        for spec in SECTION_SPECS
    }
    bpy.context.scene["turn_section_legend_json"] = json.dumps(legend, sort_keys=True)
    bpy.context.scene["turn_section_note"] = (
        "Turn count starts at the basal opening. The original generated meshes are hidden "
        "as UNSEGMENTED_GENERATED_MASTER objects. Reference collections are hidden by "
        "default for clarity but remain in the file with their transforms unchanged."
    )

    report = {
        "source_blend": str(args.input),
        "output_blend": str(args.output),
        "method": "nearest exact procedural centerline; angular turns counted from basal opening",
        "boundaries_turns": [1.0, 1.5, 2.0],
        "legend": legend,
        "records": records,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bpy.context.scene["turn_section_report"] = str(args.report)
    rendered = render_if_possible(args.render)
    bpy.context.scene["turn_section_render"] = str(args.render) if rendered else ""
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))


if __name__ == "__main__":
    main()

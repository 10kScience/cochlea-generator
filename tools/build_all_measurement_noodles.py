"""Build a two-row scene for every generatable Measurements-tab taxon.

The original six validated specimens occupy the first row. Seven additional
taxa with complete Cl/Cw/W2/#T/Ch measurements occupy the second row. Each
generated cochlea remains one intact mesh and receives the same continuous
30%-diameter, color-coded turn noodle used by the v24 inspection file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
for directory in (PROJECT_DIR, SCRIPT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cochlea_generator import CochleaParams, generate_cochlea  # noqa: E402
from build_turn_noodle_inspection import (  # noqa: E402
    NOODLE_DIAMETER_RATIO,
    NOODLE_SECTION_SPECS,
    create_noodle,
    extended_centerline,
    final_centerline,
    noodle_material,
)


TOP_ROW_KEYS = (
    "Aetiocetus",
    "Echovenator",
    "Semirostrum",
    "Squalodon",
    "Zygorhiza",
    "Scaphokogia",
)


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_generator_v24_turn_noodles.blend",
    )
    parser.add_argument(
        "--presets",
        type=Path,
        default=PROJECT_DIR / "presets/additional_measurement_specimens_v24.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_generator_v24_all_measurements.blend",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_DIR / "output/all_measurements_report_v24.json",
    )
    parser.add_argument(
        "--render",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_all_measurements_v24.png",
    )
    return parser.parse_args(raw)


def remove_studio_and_labels() -> None:
    for obj in list(bpy.data.objects):
        if obj.type in {"CAMERA", "LIGHT", "FONT"}:
            bpy.data.objects.remove(obj, do_unlink=True)


def remove_collection_recursive(collection: bpy.types.Collection) -> None:
    for child in list(collection.children):
        remove_collection_recursive(child)
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def collection_meshes(name: str) -> list[bpy.types.Object]:
    collection = bpy.data.collections.get(name)
    if collection is None:
        return []
    return [obj for obj in collection.all_objects if obj.type == "MESH"]


def move_collection(name: str, delta: Vector) -> None:
    collection = bpy.data.collections.get(name)
    if collection is None:
        return
    for obj in collection.all_objects:
        obj.location += delta


def top_row_generated(key: str) -> bpy.types.Object:
    objects = collection_meshes(f"02_{key}_Generated_RIGHT")
    if len(objects) != 1:
        raise RuntimeError(f"Expected one generated top-row mesh for {key}")
    return objects[0]


def relocate_top_pair(key: str, target: Vector) -> None:
    generated = top_row_generated(key)
    delta = target - generated.location
    for collection_name in (
        f"00_{key}_Full_Reference",
        f"01_{key}_Cochlea_Segment",
        f"02_{key}_Generated_RIGHT",
        f"TURN_NOODLE_{key}",
    ):
        move_collection(collection_name, delta)


def label_material() -> bpy.types.Material:
    material = bpy.data.materials.get("All Measurements Labels")
    if material is None:
        material = bpy.data.materials.new("All Measurements Labels")
        material.diffuse_color = (0.80, 0.86, 0.94, 1.0)
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is not None:
            principled.inputs["Base Color"].default_value = material.diffuse_color
            principled.inputs["Roughness"].default_value = 0.45
            if "Emission Color" in principled.inputs:
                principled.inputs["Emission Color"].default_value = material.diffuse_color
            if "Emission Strength" in principled.inputs:
                principled.inputs["Emission Strength"].default_value = 0.25
    return material


def add_label(
    text: str,
    position: Vector,
    collection: bpy.types.Collection,
    size: float = 1.05,
) -> None:
    curve = bpy.data.curves.new(f"{text}_LabelCurve", type="FONT")
    curve.body = text
    curve.align_x = "CENTER"
    curve.align_y = "TOP_BASELINE"
    curve.size = size
    curve.space_line = 0.85
    curve.extrude = 0.012
    curve.materials.append(label_material())
    obj = bpy.data.objects.new(f"LABEL | {text}", curve)
    obj.location = position
    collection.objects.link(obj)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (
        Vector(tuple(min(point[axis] for point in points) for axis in range(3))),
        Vector(tuple(max(point[axis] for point in points) for axis in range(3))),
    )


def build_studio(objects: list[bpy.types.Object], center: Vector, width: float, height: float) -> None:
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("All Measurements World")
        scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.018, 0.018, 0.021, 1.0)
        background.inputs["Strength"].default_value = 0.55

    aspect = 2.25
    bpy.ops.object.camera_add(location=center + Vector((0.0, 0.0, 130.0)))
    camera = bpy.context.object
    camera.name = "All Measurements Camera"
    camera.data.type = "ORTHO"
    # Blender's orthographic scale is the camera's horizontal span for this
    # landscape render. Ensure the implied vertical span also fits both rows.
    camera.data.ortho_scale = max(width * 1.16, height * aspect * 1.18)
    look_at(camera, center)
    scene.camera = camera

    for name, energy, location, size in (
        ("All Measurements Key", 4200.0, center + Vector((-35.0, -20.0, 80.0)), 42.0),
        ("All Measurements Fill", 2600.0, center + Vector((45.0, 25.0, 62.0)), 48.0),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        look_at(light, center)

    scene.render.resolution_x = 2400
    scene.render.resolution_y = 1067
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"


def render_workbench(path: Path) -> None:
    scene = bpy.context.scene
    original_engine = scene.render.engine
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    scene.render.engine = original_engine


def column_centers(widths: list[float], gap: float) -> list[float]:
    total = sum(widths) + gap * (len(widths) - 1)
    cursor = -total * 0.5
    centers: list[float] = []
    for width in widths:
        centers.append(cursor + width * 0.5)
        cursor += width + gap
    return centers


def main() -> None:
    args = parse_args()
    args.input = args.input.expanduser().resolve()
    args.presets = args.presets.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.report = args.report.expanduser().resolve()
    args.render = args.render.expanduser().resolve()
    for path in (args.output.parent, args.report.parent, args.render.parent):
        path.mkdir(parents=True, exist_ok=True)

    payload = json.loads(args.presets.read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    remove_studio_and_labels()
    for stale_name in ("ALL_MEASUREMENTS_ADDITIONAL", "ALL_MEASUREMENTS_LABELS"):
        stale = bpy.data.collections.get(stale_name)
        if stale is not None:
            remove_collection_recursive(stale)

    root = bpy.data.collections.get("Cochlea_Segmented_Overlay_QA")
    if root is None:
        root = bpy.context.scene.collection
    additional_root = bpy.data.collections.new("ALL_MEASUREMENTS_ADDITIONAL")
    labels = bpy.data.collections.new("ALL_MEASUREMENTS_LABELS")
    root.children.link(additional_root)
    root.children.link(labels)

    materials = [noodle_material(spec) for spec in NOODLE_SECTION_SPECS]
    additional: list[dict[str, object]] = []
    for mapping in payload["presets"]:
        params = CochleaParams.from_mapping(mapping)
        collection, metrics = generate_cochlea(
            params,
            parent_collection=additional_root,
            replace_existing=True,
        )
        generated_objects = [obj for obj in collection.all_objects if obj.type == "MESH"]
        if len(generated_objects) != 1:
            raise RuntimeError(f"Expected one generated mesh for {params.species_name}")
        generated = generated_objects[0]
        path = final_centerline(params, metrics)
        path, progress = extended_centerline(generated, path, params.turns)
        key = str(mapping.get("common_name") or params.species_name.split()[0])
        noodle_collection = bpy.data.collections.new(f"TURN_NOODLE_{key.replace(' ', '_')}")
        additional_root.children.link(noodle_collection)
        noodle, noodle_record = create_noodle(
            generated,
            noodle_collection,
            f"{key} | TURN COUNT NOODLE",
            path,
            progress,
            params,
            metrics,
            materials,
        )
        additional.append(
            {
                "mapping": mapping,
                "params": params,
                "collection": collection,
                "generated": generated,
                "noodle": noodle,
                "metrics": metrics,
                "noodle_record": noodle_record,
            }
        )

    top_widths = [top_row_generated(key).dimensions.x for key in TOP_ROW_KEYS]
    bottom_widths = [float(item["params"].cochlear_width_mm) for item in additional]
    top_x_positions = column_centers(top_widths, gap=6.0)
    bottom_x_positions = column_centers(bottom_widths, gap=6.0)
    top_y = 14.0
    bottom_y = -14.0

    top_names = {
        "Aetiocetus": ("Aetiocetus", 2.36),
        "Echovenator": ("Echovenator", 2.00),
        "Semirostrum": ("Semirostrum", 1.84),
        "Squalodon": ("Squalodon", 1.86),
        "Zygorhiza": ("Zygorhiza", 2.37),
        "Scaphokogia": ("Scaphokogia", 1.89),
    }
    for key, x_position in zip(TOP_ROW_KEYS, top_x_positions):
        relocate_top_pair(key, Vector((x_position, top_y, 0.0)))
        name, turns = top_names[key]
        add_label(
            f"{name}\n{turns:.2f} turns",
            Vector((x_position, top_y - 9.0, 0.25)),
            labels,
        )

    records: list[dict[str, object]] = []
    for item, x_position in zip(additional, bottom_x_positions):
        params = item["params"]
        location = Vector((x_position, bottom_y, 0.0))
        item["generated"].location += location
        item["noodle"].location += location
        mapping = item["mapping"]
        common_name = str(mapping.get("common_name") or params.species_name.split()[0])
        add_label(
            f"{common_name}\n{params.turns:.2f} turns",
            Vector((x_position, bottom_y - 15.7, 0.25)),
            labels,
        )
        metrics = item["metrics"]
        records.append(
            {
                "common_name": common_name,
                "species_name": params.species_name,
                "specimen": params.specimen,
                "parameters": {
                    "Cl_mm": params.cochlear_length_mm,
                    "Cw_mm": params.cochlear_width_mm,
                    "W2_mm": params.basal_width_perp_mm,
                    "turns": params.turns,
                    "Ch_mm": params.cochlear_height_mm,
                    "ITD_mm": params.interturn_distance_mm,
                    "SBL_extent_pct": params.secondary_lamina_extent_pct,
                    "GAN_mm": params.spiral_ganglion_diameter_mm,
                    "FC_mm2": params.fenestra_area_mm2,
                },
                "measurement_note": mapping.get("measurement_note", ""),
                "validation": {
                    "centerline_length_error_pct": metrics["centerline_length_error_pct"],
                    "actual_full_envelope_height_error_mm": metrics[
                        "actual_full_envelope_height_error_mm"
                    ],
                    "basal_opening_single_clean_loop": metrics[
                        "basal_opening_single_clean_loop"
                    ],
                    "mesh_face_count": len(item["generated"].data.polygons),
                    "cochlea_unsegmented": True,
                },
                "noodle": item["noodle_record"],
            }
        )

    visible_objects: list[bpy.types.Object] = []
    for key in TOP_ROW_KEYS:
        visible_objects.append(top_row_generated(key))
        visible_objects.extend(collection_meshes(f"TURN_NOODLE_{key}"))
    for item in additional:
        visible_objects.extend((item["generated"], item["noodle"]))
    visible_objects.extend(obj for obj in labels.objects if obj.type == "FONT")
    bpy.context.view_layer.update()
    minimum, maximum = bounds(visible_objects)
    center = (minimum + maximum) * 0.5
    size = maximum - minimum
    build_studio(visible_objects, center, size.x, size.y)
    render_workbench(args.render)

    report = {
        "generator_version": "0.24.0",
        "source_blend": str(args.input),
        "preset_file": str(args.presets),
        "layout": "original six in top row; seven additional complete-measurement taxa below",
        "noodle_diameter_ratio": NOODLE_DIAMETER_RATIO,
        "measurement_policy": payload["measurement_policy"],
        "excluded": payload["excluded"],
        "records": records,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bpy.context.scene["all_measurements_report"] = str(args.report)
    bpy.context.scene["measurement_reconciliation"] = payload["measurement_policy"]
    bpy.context.scene["excluded_measurements_json"] = json.dumps(payload["excluded"])
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))


if __name__ == "__main__":
    main()

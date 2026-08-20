"""Generate specimen presets, exports, a Blender scene, and a QA render.

Example:
    blender --background --python batch_generate.py -- \
      --presets presets/reference_specimens.json \
      --blend output/cochlea_reference_v24.blend \
      --glb-dir output/glb_v24 \
      --render output/cochlea_reference_v24.png \
      --report output/validation_report_v24.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cochlea_generator import CochleaParams, generate_cochlea  # noqa: E402


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--presets",
        type=Path,
        default=SCRIPT_DIR / "presets" / "reference_specimens.json",
    )
    parser.add_argument(
        "--blend",
        type=Path,
        default=SCRIPT_DIR / "output" / "cochlea_reference_v24.blend",
    )
    parser.add_argument(
        "--glb-dir",
        type=Path,
        default=SCRIPT_DIR / "output" / "glb_v24",
    )
    parser.add_argument(
        "--render",
        type=Path,
        default=SCRIPT_DIR / "output" / "cochlea_reference_v24.png",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=SCRIPT_DIR / "output" / "validation_report_v24.json",
    )
    return parser.parse_args(raw)


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def collection_bounds(collection: bpy.types.Collection) -> tuple[Vector, Vector]:
    points = [
        obj.matrix_world @ Vector(corner)
        for obj in collection.all_objects
        if obj.type in {"MESH", "FONT"}
        for corner in obj.bound_box
    ]
    minimum = Vector(
        (
            min(point.x for point in points),
            min(point.y for point in points),
            min(point.z for point in points),
        )
    )
    maximum = Vector(
        (
            max(point.x for point in points),
            max(point.y for point in points),
            max(point.z for point in points),
        )
    )
    return minimum, maximum


def select_collection(collection: bpy.types.Collection) -> list[bpy.types.Object]:
    bpy.ops.object.select_all(action="DESELECT")
    objects = [obj for obj in collection.all_objects if obj.type == "MESH"]
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    return objects


def export_collection_glb(collection: bpy.types.Collection, output_path: Path) -> None:
    objects = select_collection(collection)
    if not objects:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    original_scales = {obj: obj.scale.copy() for obj in objects}
    try:
        # glTF coordinates are metres. Generator coordinates are millimetres,
        # so bake a 0.001 export scale without changing the Blender source.
        for obj in objects:
            obj.scale *= 0.001
        bpy.context.view_layer.update()
        bpy.ops.export_scene.gltf(
            filepath=str(output_path),
            export_format="GLB",
            use_selection=True,
            export_apply=True,
            export_yup=True,
        )
    finally:
        for obj, scale in original_scales.items():
            obj.scale = scale
        bpy.context.view_layer.update()


def validate_collection_meshes(collection: bpy.types.Collection) -> dict[str, object]:
    parts = []
    non_manifold_total = 0
    for obj in collection.all_objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
        wire_edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
        junction_edges = [edge for edge in bm.edges if len(edge.link_faces) > 2]
        non_manifold_edges = len(boundary_edges) + len(wire_edges) + len(junction_edges)
        boundary_adjacency: dict[object, set[object]] = {}
        for edge in boundary_edges:
            first, second = edge.verts
            boundary_adjacency.setdefault(first, set()).add(second)
            boundary_adjacency.setdefault(second, set()).add(first)
        boundary_unvisited = set(boundary_adjacency)
        boundary_components = 0
        closed_boundary_loops = 0
        while boundary_unvisited:
            boundary_components += 1
            start = boundary_unvisited.pop()
            stack = [start]
            component = {start}
            while stack:
                vertex = stack.pop()
                for neighbor in boundary_adjacency.get(vertex, set()):
                    if neighbor in boundary_unvisited:
                        boundary_unvisited.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
            if component and all(
                len(boundary_adjacency[vertex]) == 2 for vertex in component
            ):
                closed_boundary_loops += 1
        unvisited = set(bm.verts)
        connected_components = 0
        component_sizes: list[int] = []
        while unvisited:
            connected_components += 1
            stack = [unvisited.pop()]
            component_size = 0
            while stack:
                vertex = stack.pop()
                component_size += 1
                for edge in vertex.link_edges:
                    neighbor = edge.other_vert(vertex)
                    if neighbor in unvisited:
                        unvisited.remove(neighbor)
                        stack.append(neighbor)
            component_sizes.append(component_size)
        parts.append(
            {
                "object": obj.name,
                "vertices": len(bm.verts),
                "faces": len(bm.faces),
                "non_manifold_edges": non_manifold_edges,
                "boundary_edges": len(boundary_edges),
                "boundary_components": boundary_components,
                "closed_boundary_loops": closed_boundary_loops,
                "wire_edges": len(wire_edges),
                "junction_edges": len(junction_edges),
                "single_clean_opening": (
                    boundary_components == 1
                    and closed_boundary_loops == 1
                    and not wire_edges
                    and not junction_edges
                ),
                "connected_components": connected_components,
                "component_vertex_counts": sorted(component_sizes, reverse=True),
            }
        )
        non_manifold_total += non_manifold_edges
        bm.free()
    return {
        "parts": parts,
        "non_manifold_edges_total": non_manifold_total,
    }


def add_text_label(
    text: str,
    location: Vector,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(f"{text}_Label_Curve", type="FONT")
    curve.body = text
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = 0.55
    curve.extrude = 0.018
    curve.bevel_depth = 0.007
    obj = bpy.data.objects.new(f"{text}_Label", curve)
    obj.location = location
    collection.objects.link(obj)

    material = bpy.data.materials.get("Label Material")
    if material is None:
        material = bpy.data.materials.new("Label Material")
        material.diffuse_color = (0.78, 0.84, 0.92, 1.0)
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled:
            principled.inputs["Base Color"].default_value = material.diffuse_color
            principled.inputs["Roughness"].default_value = 0.50
    curve.materials.append(material)
    return obj


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_studio_scene(width: float, height: float, center: Vector) -> None:
    scene = bpy.context.scene
    world = scene.world
    world.color = (0.010, 0.016, 0.026)
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.010, 0.016, 0.026, 1.0)
        background.inputs["Strength"].default_value = 0.70

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(height * 1.78, width * 1.00)
    camera.location = center + Vector((0.0, -height * 0.68, height * 2.12))
    look_at(camera, center + Vector((0.0, 0.0, 0.3)))
    scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=camera.location + Vector((0.0, 0.0, 3.0)))
    camera_fill = bpy.context.object
    camera_fill.data.energy = 2400.0
    camera_fill.data.shape = "DISK"
    camera_fill.data.size = max(width, height) * 0.72
    look_at(camera_fill, center + Vector((0.0, 0.0, 1.0)))

    for energy, size, location in [
        (1450.0, 13.0, Vector((-12.0, -15.0, 25.0))),
        (940.0, 10.0, Vector((17.0, 8.0, 15.0))),
        (680.0, 8.0, Vector((-18.0, 14.0, 8.0))),
    ]:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.location += center
        look_at(light, center + Vector((0.0, 0.0, 2.0)))

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1100
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"


def main() -> None:
    args = parse_args()
    args.presets = args.presets.expanduser().resolve()
    args.blend = args.blend.expanduser().resolve()
    args.glb_dir = args.glb_dir.expanduser().resolve()
    args.render = args.render.expanduser().resolve()
    args.report = args.report.expanduser().resolve()
    for path in (args.blend.parent, args.glb_dir, args.render.parent, args.report.parent):
        path.mkdir(parents=True, exist_ok=True)

    payload = json.loads(args.presets.read_text(encoding="utf-8"))
    reset_scene()
    root = bpy.data.collections.new("Generated_Cochleae")
    bpy.context.scene.collection.children.link(root)

    records: list[dict[str, object]] = []
    generated: list[tuple[CochleaParams, bpy.types.Collection]] = []
    for mapping in payload["presets"]:
        params = CochleaParams.from_mapping(mapping)
        collection, metrics = generate_cochlea(
            params,
            parent_collection=root,
            replace_existing=True,
        )
        export_path = args.glb_dir / f"{collection.name}.glb"
        export_collection_glb(collection, export_path)
        minimum, maximum = collection_bounds(collection)
        records.append(
            {
                "species_name": params.species_name,
                "specimen": params.specimen,
                "parameters": {
                    "cochlear_length_mm": params.cochlear_length_mm,
                    "cochlear_width_mm": params.cochlear_width_mm,
                    "basal_width_perp_mm": params.basal_width_perp_mm,
                    "turns": params.turns,
                    "cochlear_height_mm": params.cochlear_height_mm,
                    "interturn_distance_mm": params.interturn_distance_mm,
                    "secondary_lamina_extent_pct": params.secondary_lamina_extent_pct,
                    "spiral_ganglion_diameter_mm": params.spiral_ganglion_diameter_mm,
                    "fenestra_area_mm2": params.fenestra_area_mm2,
                },
                "shape_policy": "shared defaults; no specimen-specific morphology tuning",
                "generated": metrics,
                "bounds_before_layout": {
                    "minimum": list(minimum),
                    "maximum": list(maximum),
                    "dimensions": list(maximum - minimum),
                },
                "mesh_validation": validate_collection_meshes(collection),
                "glb": str(export_path),
                "glb_units": "metres (physical dimensions preserve the millimetre inputs)",
            }
        )
        generated.append((params, collection))

    max_width = max(params.cochlear_width_mm for params, _collection in generated)
    max_depth = max(params.basal_width_perp_mm for params, _collection in generated)
    column_spacing = max_width * 1.52
    row_spacing = max_depth * 1.75 + 2.0
    column_count = max(1, math.ceil(math.sqrt(len(generated))))
    row_count = max(1, math.ceil(len(generated) / column_count))
    layout_positions = []
    for index in range(len(generated)):
        column = index % column_count
        row = index // column_count
        layout_positions.append(
            Vector(
                (
                    (column - (column_count - 1) * 0.5) * column_spacing,
                    ((row_count - 1) * 0.5 - row) * row_spacing,
                    0.0,
                )
            )
        )

    for (params, collection), location in zip(generated, layout_positions):
        for obj in collection.all_objects:
            obj.location += location
        short_name = params.species_name.split()[0]
        label = f"{short_name}  |  {params.turns:.2f} turns"
        add_text_label(
            label,
            location + Vector((0.0, -max_depth * 0.76, -0.10)),
            root,
        )

    bpy.context.view_layer.update()
    overall_min, overall_max = collection_bounds(root)
    overall_size = overall_max - overall_min
    add_studio_scene(overall_size.x, overall_size.y, (overall_min + overall_max) * 0.5)

    args.render.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(args.render)
    bpy.ops.render.render(write_still=True)

    args.report.write_text(
        json.dumps(
            {
                "generator_version": "0.24.0",
                "preset_file": str(args.presets),
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    bpy.context.scene["cochlea_validation_report"] = str(args.report)
    args.blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.blend))


if __name__ == "__main__":
    main()

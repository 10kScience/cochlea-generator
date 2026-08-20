"""Build optional hollow visualization shells from the stable v32 cochleae.

The source v32 assets are not modified. This post-process preserves the outer
body, regularizes only the terminal boundary loop, adds a centerline-following
inner surface and outward-rolled basal lip, then exports co-registered
cochlea/noodle GLB pairs to a new directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
for directory in (PROJECT_DIR, SCRIPT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cochlea_generator import CochleaParams  # noqa: E402
from inner_liner_shell import (  # noqa: E402
    DEFAULT_INNER_RADIUS_RATIO,
    DEFAULT_ORGANIC_AMPLITUDE_RATIO,
    add_inner_liner,
)
from build_turn_noodle_inspection import split_noodle_by_material  # noqa: E402


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-blend",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_normalized_exports_v32.blend",
    )
    parser.add_argument(
        "--input-report",
        type=Path,
        default=PROJECT_DIR / "output/glb_normalized_v32_report.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_DIR / "output/glb_normalized_v37_three_section_noodles",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=PROJECT_DIR / "output/glb_normalized_v37_three_section_noodles_report.json",
    )
    parser.add_argument(
        "--output-blend",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_normalized_exports_v37_three_section_noodles.blend",
    )
    parser.add_argument(
        "--output-render",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_normalized_exports_v37_three_section_noodles.png",
    )
    parser.add_argument(
        "--inner-radius-ratio",
        type=float,
        default=DEFAULT_INNER_RADIUS_RATIO,
    )
    parser.add_argument(
        "--organic-displacement",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--organic-amplitude-ratio",
        type=float,
        default=DEFAULT_ORGANIC_AMPLITUDE_RATIO,
        help="RMS geometric displacement as a fraction of measured Cw",
    )
    return parser.parse_args(raw)


def export_selected(
    objects: bpy.types.Object | list[bpy.types.Object], path: Path
) -> None:
    if isinstance(objects, bpy.types.Object):
        objects = [objects]
    if not objects:
        raise RuntimeError(f"{path.name}: no objects selected for export")
    original_states = [
        (
            obj,
            obj.matrix_world.copy(),
            obj.hide_render,
            obj.hide_viewport,
            obj.hide_get(),
        )
        for obj in objects
    ]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.matrix_world = Matrix.Identity(4)
        obj.hide_viewport = False
        obj.hide_render = False
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.context.view_layer.update()
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_materials="EXPORT",
        export_normals=True,
        export_extras=True,
        export_cameras=False,
        export_lights=False,
    )
    for obj, matrix, hide_render, hide_viewport, hidden in original_states:
        obj.matrix_world = matrix
        obj.hide_viewport = hide_viewport
        obj.hide_render = hide_render
        obj.hide_set(hidden)
        obj.select_set(False)


def generated_collections() -> dict[str, tuple[bpy.types.Collection, CochleaParams, dict[str, object]]]:
    result = {}
    for collection in bpy.data.collections:
        if "parameters_json" not in collection or "metrics_json" not in collection:
            continue
        params = CochleaParams.from_mapping(json.loads(collection["parameters_json"]))
        metrics = json.loads(collection["metrics_json"])
        result[params.species_name] = (collection, params, metrics)
    return result


def main() -> None:
    args = parse_args()
    for attribute in (
        "input_blend",
        "input_report",
        "output_dir",
        "output_report",
        "output_blend",
        "output_render",
    ):
        setattr(args, attribute, getattr(args, attribute).expanduser().resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path in (args.output_report, args.output_blend, args.output_render):
        path.parent.mkdir(parents=True, exist_ok=True)

    source_report = json.loads(args.input_report.read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(args.input_blend))
    collections = generated_collections()
    output_records = []

    for source_record in source_report["records"]:
        record = copy.deepcopy(source_record)
        species_name = str(record["species_name"])
        collection, params, metrics = collections[species_name]
        cochlea_candidates = [
            obj
            for obj in collection.objects
            if obj.type == "MESH" and obj.name.endswith("_Cochlea")
        ]
        if len(cochlea_candidates) != 1:
            raise RuntimeError(
                f"{species_name}: expected one generated cochlea, found {len(cochlea_candidates)}"
            )
        source = cochlea_candidates[0]
        hollow, shell_stats = add_inner_liner(
            source,
            params,
            metrics,
            inner_radius_ratio=args.inner_radius_ratio,
            organic_displacement=args.organic_displacement,
            organic_amplitude_ratio=args.organic_amplitude_ratio,
        )
        hollow.name = f"{source.name}_Hollow"
        hollow.data.name = f"{hollow.name}_Mesh"
        source.hide_render = True
        source.hide_viewport = True
        source.hide_set(True)
        hollow.hide_render = False
        hollow.hide_viewport = False
        hollow.hide_set(False)

        noodle_name = str(record["noodle"]["object"])
        noodle = bpy.data.objects.get(noodle_name)
        if noodle is None:
            raise RuntimeError(f"{species_name}: could not find {noodle_name}")
        cochlea_filename = Path(record["cochlea"]["file"]).name
        noodle_filename = Path(record["noodle"]["file"]).name
        cochlea_path = args.output_dir / cochlea_filename
        noodle_path = args.output_dir / noodle_filename
        export_selected(hollow, cochlea_path)
        noodle_segments = split_noodle_by_material(noodle)
        export_selected(noodle_segments, noodle_path)

        record["cochlea"].update(
            {
                "file": str(cochlea_path),
                "bytes": cochlea_path.stat().st_size,
                "vertices": len(hollow.data.vertices),
                "polygons": len(hollow.data.polygons),
                "triangles": int(shell_stats["triangles"]),
                "optimization": "v32 25k outer shell plus procedural inner liner",
                "closed_inner_liner": True,
                "closed_manifold": bool(shell_stats["closed_manifold"]),
                "inner_radius_ratio": float(shell_stats["inner_radius_ratio"]),
                "outer_body_preserved": True,
                "basal_boundary_smoothed": bool(
                    shell_stats["basal_boundary_smoothed"]
                ),
                "lip_direction": "outward",
                "organic_displacement": bool(
                    shell_stats["organic_displacement"]
                ),
                "organic_displacement_algorithm": (
                    "three-scale deterministic fractal Brownian motion"
                    if args.organic_displacement
                    else "none"
                ),
                "organic_displacement_amplitude_ratio_Cw": (
                    args.organic_amplitude_ratio
                ),
                "outer_faces_preserved": int(shell_stats["outer_faces_preserved"]),
                "basal_boundary_vertices": int(shell_stats["basal_boundary_vertices"]),
                "centerline_rings": int(shell_stats["centerline_rings"]),
            }
        )
        for key, value in shell_stats.items():
            if key.startswith("organic_") and key not in record["cochlea"]:
                record["cochlea"][key] = value
        record["cochlea"].pop("basal_opening_single_clean_loop", None)
        record["noodle"]["file"] = str(noodle_path)
        record["noodle"]["bytes"] = noodle_path.stat().st_size
        record["noodle"]["segmented_meshes"] = True
        record["noodle"]["mesh_count"] = len(noodle_segments)
        record["noodle"]["objects"] = [obj.name for obj in noodle_segments]
        record["noodle"]["section_keys"] = [
            str(obj["turn_section_key"]) for obj in noodle_segments
        ]
        record["noodle"]["vertices"] = sum(
            len(obj.data.vertices) for obj in noodle_segments
        )
        record["noodle"]["polygons"] = sum(
            len(obj.data.polygons) for obj in noodle_segments
        )
        output_records.append(record)
        print(
            "HOLLOW_EXPORT",
            record["common_name"],
            shell_stats["triangles"],
            "triangles",
            cochlea_path.name,
        )

    scene = bpy.context.scene
    # An opaque closed shell self-shadows heavily in Eevee. Use neutral
    # Workbench lighting for the geometry contact sheet; the delivery GLBs keep
    # their ordinary material for the application's transparent rim shader.
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.studio_light = "paint.sl"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.render.filepath = str(args.output_render)
    bpy.ops.render.render(write_still=True)

    output_report = {
        **{
            key: value
            for key, value in source_report.items()
            if key not in {"records", "output_directory", "generator_version"}
        },
        "generator_version": "0.37.0",
        "source_generator_version": source_report.get("generator_version"),
        "shell_policy": (
            "closed centerline inner liner with smoothed outward-rolled basal lip"
        ),
        "inner_radius_ratio": args.inner_radius_ratio,
        "organic_displacement": args.organic_displacement,
        "organic_displacement_algorithm": (
            "three deterministic physical-scale fBm layers displaced along "
            "smooth vertex normals"
        ),
        "organic_displacement_amplitude_ratio_Cw": args.organic_amplitude_ratio,
        "organic_displacement_layer_weights": {
            "macro": 0.55,
            "meso": 0.32,
            "micro": 0.13,
        },
        "noodle_mesh_policy": (
            "three single-material ranges: purple 0-1, orange 1-2, green 2+"
        ),
        "outer_surface_policy": (
            "v32 outer body preserved; only the final basal boundary loop is smoothed"
        ),
        "output_directory": str(args.output_dir),
        "file_count": len(output_records) * 2,
        "records": output_records,
    }
    args.output_report.write_text(
        json.dumps(output_report, indent=2) + "\n", encoding="utf-8"
    )
    scene["normalized_export_report"] = str(args.output_report)
    scene["inner_liner_ratio"] = args.inner_radius_ratio
    scene["outer_body_preserved"] = True
    scene["basal_boundary_smoothed"] = True
    scene["lip_direction"] = "outward"
    scene["organic_displacement"] = args.organic_displacement
    scene["organic_displacement_amplitude_ratio_Cw"] = (
        args.organic_amplitude_ratio
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output_blend))


if __name__ == "__main__":
    main()

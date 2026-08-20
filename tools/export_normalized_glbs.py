"""Generate normalized cochleae and export isolated cochlea/noodle GLBs.

Every specimen is generated from the same measurement-driven morphology and
the same scale-normalized voxel policy.  Two files are exported per specimen:
one cochlea-only GLB and one turn-noodle-only GLB.  Because both exports retain
the same coordinate system, they align when loaded together.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
for directory in (PROJECT_DIR, SCRIPT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from build_all_measurement_noodles import (  # noqa: E402
    add_label,
    bounds,
    build_studio,
    column_centers,
    render_workbench,
)
from build_turn_noodle_inspection import (  # noqa: E402
    NOODLE_DIAMETER_RATIO,
    NOODLE_SECTION_SPECS,
    create_noodle,
    extended_centerline,
    final_centerline,
    noodle_material,
)
from cochlea_generator import CochleaParams, generate_cochlea  # noqa: E402


REFERENCE_COMMON_NAMES = {
    "cf. Aetiocetus": "Aetiocetus",
    "Echovenator sandersi": "Echovenator",
    "Scaphokogia cochlearis": "Scaphokogia",
    "Semirostrum ceruttii": "Semirostrum",
    "Squalodon calvertensis": "Squalodon",
    "Zygorhiza kochii": "Zygorhiza",
}

HIGH_DETAIL_COMMON_NAMES = {"Vaquita", "Blue whale", "Orca"}
STANDARD_RADIAL_SEGMENTS = 56
STANDARD_LONGITUDINAL_SAMPLES = 520
HIGH_DETAIL_VOXELS_ACROSS_CW = 300
HIGH_DETAIL_RADIAL_SEGMENTS = 80
HIGH_DETAIL_LONGITUDINAL_SAMPLES = 800
COCHLEA_TARGET_TRIANGLES = 25_000


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reference-presets",
        type=Path,
        default=PROJECT_DIR / "presets/reference_specimens.json",
    )
    parser.add_argument(
        "--additional-presets",
        type=Path,
        default=PROJECT_DIR / "presets/additional_measurement_specimens_v24.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_DIR / "output/glb_normalized_v32",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_DIR / "output/glb_normalized_v32_report.json",
    )
    parser.add_argument(
        "--blend",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_normalized_exports_v32.blend",
    )
    parser.add_argument(
        "--render",
        type=Path,
        default=PROJECT_DIR / "output/cochlea_normalized_exports_v32.png",
    )
    return parser.parse_args(raw)


def slugify(value: str) -> str:
    value = value.lower().replace("cf.", "")
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value or "cochlea"


def triangle_count(obj: bpy.types.Object) -> int:
    return sum(max(1, len(polygon.vertices) - 2) for polygon in obj.data.polygons)


def collapse_decimate_to_target(
    obj: bpy.types.Object, target_triangles: int
) -> tuple[int, int]:
    """Apply Blender's topology-preserving collapse decimator to one shell."""

    before = triangle_count(obj)
    if before <= target_triangles:
        return before, before
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Collapse Decimate 25k", "DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = _clamp_ratio(target_triangles / max(float(before), 1.0))
    modifier.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return before, triangle_count(obj)


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def mirror_mesh_x(obj: bpy.types.Object) -> None:
    """Bake an X reflection while preserving outward face winding."""

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for vertex in bm.verts:
        vertex.co.x = -vertex.co.x
    if bm.faces:
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()


def export_selected(obj: bpy.types.Object, path: Path) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_render = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
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


def load_presets(reference_path: Path, additional_path: Path) -> list[dict[str, object]]:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))["presets"]
    additional = json.loads(additional_path.read_text(encoding="utf-8"))["presets"]
    combined: list[dict[str, object]] = []
    for mapping in reference:
        item = dict(mapping)
        item["common_name"] = REFERENCE_COMMON_NAMES.get(
            str(mapping["species_name"]), str(mapping["species_name"]).split()[0]
        )
        combined.append(item)
    combined.extend(dict(mapping) for mapping in additional)
    return combined


def add_metadata(
    obj: bpy.types.Object,
    params: CochleaParams,
    metrics: dict[str, object],
    asset_role: str,
) -> None:
    obj["asset_role"] = asset_role
    obj["species_name"] = params.species_name
    obj["specimen"] = params.specimen
    obj["cochlear_length_mm"] = params.cochlear_length_mm
    obj["cochlear_width_mm"] = params.cochlear_width_mm
    obj["cochlear_height_mm"] = params.cochlear_height_mm
    obj["turns"] = params.turns
    obj["handedness"] = params.handedness
    obj["voxel_size_mm"] = float(metrics["voxel_size_mm"])
    obj["voxel_size_policy"] = (
        f"{params.voxels_across_cochlear_width} voxels across Cw"
        if params.normalize_voxel_size
        else "manual physical voxel size"
    )


def main() -> None:
    args = parse_args()
    args.reference_presets = args.reference_presets.expanduser().resolve()
    args.additional_presets = args.additional_presets.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.report = args.report.expanduser().resolve()
    args.blend = args.blend.expanduser().resolve()
    args.render = args.render.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path in (args.report, args.blend, args.render):
        path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    root = bpy.data.collections.new("NORMALIZED_COCHLEA_EXPORTS")
    labels = bpy.data.collections.new("NORMALIZED_EXPORT_LABELS")
    scene.collection.children.link(root)
    scene.collection.children.link(labels)
    materials = [noodle_material(spec) for spec in NOODLE_SECTION_SPECS]

    generated: list[dict[str, object]] = []
    for mapping in load_presets(args.reference_presets, args.additional_presets):
        params = CochleaParams.from_mapping(mapping)
        params = replace(
            params,
            handedness="RIGHT",
            radial_segments=STANDARD_RADIAL_SEGMENTS,
            longitudinal_samples=STANDARD_LONGITUDINAL_SAMPLES,
        )
        common_name = str(mapping.get("common_name") or params.species_name.split()[0])
        if common_name in HIGH_DETAIL_COMMON_NAMES:
            params = replace(
                params,
                voxels_across_cochlear_width=HIGH_DETAIL_VOXELS_ACROSS_CW,
                radial_segments=HIGH_DETAIL_RADIAL_SEGMENTS,
                longitudinal_samples=HIGH_DETAIL_LONGITUDINAL_SAMPLES,
            )
        collection, metrics = generate_cochlea(
            params,
            parent_collection=root,
            replace_existing=True,
        )
        cochlea_meshes = [obj for obj in collection.all_objects if obj.type == "MESH"]
        if len(cochlea_meshes) != 1:
            raise RuntimeError(
                f"Expected one cochlea mesh for {params.species_name}; "
                f"found {len(cochlea_meshes)}"
            )
        cochlea = cochlea_meshes[0]
        path = final_centerline(params, metrics)
        path, progress = extended_centerline(cochlea, path, params.turns)
        slug = slugify(common_name)
        noodle_collection = bpy.data.collections.new(f"TURN_NOODLE_{slug}")
        root.children.link(noodle_collection)
        noodle, noodle_record = create_noodle(
            cochlea,
            noodle_collection,
            f"{common_name} | TURN COUNT NOODLE",
            path,
            progress,
            params,
            metrics,
            materials,
        )
        # The historical Blender scene used the mirrored (left) display
        # convention. Bake an X reflection into both isolated assets so every
        # exported pair is anatomical RIGHT without negative object scale.
        mirror_mesh_x(cochlea)
        mirror_mesh_x(noodle)
        spiral_origin = noodle_record.get("spiral_origin_local")
        if isinstance(spiral_origin, list) and len(spiral_origin) == 3:
            spiral_origin[0] = -float(spiral_origin[0])
        add_metadata(cochlea, params, metrics, "cochlea")
        add_metadata(noodle, params, metrics, "turn-count noodle")
        pre_decimate_triangles, post_decimate_triangles = collapse_decimate_to_target(
            cochlea, COCHLEA_TARGET_TRIANGLES
        )
        cochlea["optimization"] = "Blender Collapse Decimate"
        cochlea["source_triangles_before_decimate"] = pre_decimate_triangles
        cochlea["target_triangles"] = COCHLEA_TARGET_TRIANGLES
        cochlea["triangles_after_decimate"] = post_decimate_triangles

        cochlea_path = args.output_dir / f"{slug}_cochlea.glb"
        noodle_path = args.output_dir / f"{slug}_noodle.glb"
        export_selected(cochlea, cochlea_path)
        export_selected(noodle, noodle_path)
        generated.append(
            {
                "common_name": common_name,
                "slug": slug,
                "params": params,
                "cochlea": cochlea,
                "noodle": noodle,
                "metrics": metrics,
                "noodle_record": noodle_record,
                "cochlea_path": cochlea_path,
                "noodle_path": noodle_path,
                "pre_decimate_triangles": pre_decimate_triangles,
                "post_decimate_triangles": post_decimate_triangles,
            }
        )

    # Arrange only after export so each pair retains an identical origin in its
    # isolated GLBs. This laid-out scene is solely for QA and handoff.
    rows = (generated[:7], generated[7:])
    row_y = (13.0, -13.0)
    for row, y in zip(rows, row_y):
        widths = [float(item["params"].cochlear_width_mm) for item in row]
        positions = column_centers(widths, gap=5.5)
        for item, x in zip(row, positions):
            offset = Vector((x, y, 0.0))
            item["cochlea"].location += offset
            item["noodle"].location += offset
            params = item["params"]
            add_label(
                f"{item['common_name']}\n{params.turns:.2f} turns",
                Vector((x, y - 8.2, 0.25)),
                labels,
                size=0.88,
            )

    # Keep separate noodle GLBs available, but hide the in-scene overlays for
    # this morphology-review version so they do not obscure the apical wrap.
    for item in generated:
        item["noodle"].hide_viewport = True
        item["noodle"].hide_render = True
        item["noodle"].hide_set(True)
    visible = [item["cochlea"] for item in generated]
    visible.extend(obj for obj in labels.objects if obj.type == "FONT")
    bpy.context.view_layer.update()
    minimum, maximum = bounds(visible)
    center = (minimum + maximum) * 0.5
    size = maximum - minimum
    build_studio(visible, center, size.x, size.y)
    render_workbench(args.render)

    records: list[dict[str, object]] = []
    for item in generated:
        params = item["params"]
        metrics = item["metrics"]
        cochlea = item["cochlea"]
        noodle = item["noodle"]
        records.append(
            {
                "common_name": item["common_name"],
                "species_name": params.species_name,
                "specimen": params.specimen,
                "measurements": {
                    "Cl_mm": params.cochlear_length_mm,
                    "Cw_mm": params.cochlear_width_mm,
                    "W2_mm": params.basal_width_perp_mm,
                    "Ch_mm": params.cochlear_height_mm,
                    "turns": params.turns,
                    "handedness": params.handedness,
                },
                "voxel_policy": {
                    "normalized": params.normalize_voxel_size,
                    "voxels_across_Cw": params.voxels_across_cochlear_width,
                    "effective_voxel_size_mm": metrics["voxel_size_mm"],
                },
                "cochlea": {
                    "file": str(item["cochlea_path"]),
                    "bytes": item["cochlea_path"].stat().st_size,
                    "vertices": len(cochlea.data.vertices),
                    "polygons": len(cochlea.data.polygons),
                    "triangles": triangle_count(cochlea),
                    "optimization": "Blender Collapse Decimate",
                    "triangles_before_decimate": item[
                        "pre_decimate_triangles"
                    ],
                    "target_triangles": COCHLEA_TARGET_TRIANGLES,
                    "basal_opening_single_clean_loop": metrics[
                        "basal_opening_single_clean_loop"
                    ],
                    "centerline_length_error_pct": metrics[
                        "centerline_length_error_pct"
                    ],
                    "height_error_mm": metrics[
                        "actual_full_envelope_height_error_mm"
                    ],
                },
                "noodle": {
                    "file": str(item["noodle_path"]),
                    "bytes": item["noodle_path"].stat().st_size,
                    "vertices": len(noodle.data.vertices),
                    "polygons": len(noodle.data.polygons),
                    "triangles": triangle_count(noodle),
                    **item["noodle_record"],
                },
            }
        )

    report = {
        "generator_version": "0.32.1",
        "coordinate_policy": (
            "Each cochlea/noodle pair shares identical local coordinates and aligns "
            "when imported together. Scene units are millimeters."
        ),
        "voxel_policy": (
            "90 voxels across measured Cw with a 56x520 sweep for standard assets; "
            "300 across Cw with an 80x800 sweep for Vaquita, Blue whale, and Orca "
            "close-up assets"
        ),
        "high_detail_common_names": sorted(HIGH_DETAIL_COMMON_NAMES),
        "high_detail_voxels_across_Cw": HIGH_DETAIL_VOXELS_ACROSS_CW,
        "cochlea_optimization": (
            "Blender Collapse Decimate to 25,000 triangles after normalized "
            "voxel generation; sharp basal opening retained"
        ),
        "cochlea_target_triangles": COCHLEA_TARGET_TRIANGLES,
        "noodle_diameter_ratio": NOODLE_DIAMETER_RATIO,
        "output_directory": str(args.output_dir),
        "file_count": len(records) * 2,
        "records": records,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    scene["normalized_export_report"] = str(args.report)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.blend))


if __name__ == "__main__":
    main()

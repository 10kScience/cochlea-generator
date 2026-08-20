"""Re-import and validate the isolated normalized cochlea/noodle GLBs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("validation", type=Path)
    return parser.parse_args(raw)


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def import_meshes(path: Path) -> list[bpy.types.Object]:
    reset_scene()
    result = bpy.ops.import_scene.gltf(filepath=str(path))
    if "FINISHED" not in result:
        raise RuntimeError(f"Could not import {path}")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"{path.name}: expected mesh objects, found none")
    return meshes


def import_single_mesh(path: Path) -> bpy.types.Object:
    meshes = import_meshes(path)
    if len(meshes) != 1:
        raise RuntimeError(f"{path.name}: expected one mesh, found {len(meshes)}")
    return meshes[0]


def aggregate_bounds(
    objects: list[bpy.types.Object],
) -> tuple[Vector, Vector]:
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in objects
        for corner in obj.bound_box
    ]
    minimum = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
    maximum = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
    return maximum - minimum, (minimum + maximum) * 0.5


def vector_tuple(value: Vector) -> list[float]:
    return [round(component, 8) for component in value]


def boundary_statistics(obj: bpy.types.Object) -> dict[str, int | bool]:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    adjacency: dict[object, set[object]] = {}
    for edge in boundary_edges:
        first, second = edge.verts
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
    unvisited = set(adjacency)
    components = 0
    closed_loops = 0
    while unvisited:
        components += 1
        start = unvisited.pop()
        component = {start}
        stack = [start]
        while stack:
            vertex = stack.pop()
            for neighbor in adjacency.get(vertex, set()):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        if component and all(len(adjacency[vertex]) == 2 for vertex in component):
            closed_loops += 1
    result = {
        "boundary_edges": len(boundary_edges),
        "boundary_components": components,
        "closed_boundary_loops": closed_loops,
        "wire_edges": sum(1 for edge in bm.edges if len(edge.link_faces) == 0),
        "junction_edges": sum(1 for edge in bm.edges if len(edge.link_faces) > 2),
    }
    result["single_clean_opening"] = (
        result["boundary_components"] == 1
        and result["closed_boundary_loops"] == 1
        and result["wire_edges"] == 0
        and result["junction_edges"] == 0
    )
    result["closed_manifold"] = (
        result["boundary_edges"] == 0
        and result["wire_edges"] == 0
        and result["junction_edges"] == 0
    )
    bm.free()
    return result


def main() -> None:
    args = parse_args()
    report = json.loads(args.report.resolve().read_text(encoding="utf-8"))
    validations: list[dict[str, object]] = []
    failures: list[str] = []
    bpy.ops.wm.read_factory_settings(use_empty=True)

    for record in report["records"]:
        name = record["common_name"]
        expects_inner_liner = bool(record["cochlea"].get("closed_inner_liner"))
        cochlea_path = Path(record["cochlea"]["file"])
        noodle_path = Path(record["noodle"]["file"])

        cochlea = import_single_mesh(cochlea_path)
        cochlea_transform = cochlea.matrix_world.copy()
        cochlea_dimensions = cochlea.dimensions.copy()
        cochlea_center = cochlea.matrix_world @ (
            sum((Vector(corner) for corner in cochlea.bound_box), Vector()) / 8.0
        )
        cochlea_opening = boundary_statistics(cochlea)
        cochlea_role = cochlea.get("asset_role")
        cochlea_species = cochlea.get("species_name")
        cochlea_handedness = cochlea.get("handedness")
        cochlea_materials = len(cochlea.data.materials)

        noodles = import_meshes(noodle_path)
        noodle_dimensions, noodle_center = aggregate_bounds(noodles)
        noodle_roles = {noodle.get("asset_role") for noodle in noodles}
        noodle_species = {noodle.get("species_name") for noodle in noodles}
        noodle_handedness = {noodle.get("handedness") for noodle in noodles}
        noodle_material_names = {
            material.name
            for noodle in noodles
            for material in noodle.data.materials
            if material is not None
        }
        noodle_materials = len(noodle_material_names)
        expects_segmented_noodle = bool(record["noodle"].get("segmented_meshes"))

        same_transform = all(
            abs(cochlea_transform[row][column] - noodle.matrix_world[row][column])
            < 1e-7
            for noodle in noodles
            for row in range(4)
            for column in range(4)
        )
        center_distance = (cochlea_center - noodle_center).length
        center_tolerance = max(cochlea_dimensions) * 0.45
        checks = {
            "cochlea_role": cochlea_role
            in {"cochlea", "cochlea hollow visualization shell"},
            "noodle_role": noodle_roles == {"turn-count noodle"},
            "matching_species": noodle_species == {cochlea_species},
            "both_right_handed": (
                cochlea_handedness == "RIGHT"
                and noodle_handedness == {"RIGHT"}
            ),
            "same_transform": same_transform,
            "pair_centers_overlap": center_distance <= center_tolerance,
            "cochlea_expected_topology": (
                cochlea_opening["closed_manifold"]
                if expects_inner_liner
                else cochlea_opening["single_clean_opening"]
            ),
            "cochlea_has_material": cochlea_materials >= 1,
            "noodle_has_section_materials": noodle_materials >= 2,
            "noodle_has_separate_section_meshes": (
                len(noodles) >= 2
                and all(len(noodle.data.materials) == 1 for noodle in noodles)
                if expects_segmented_noodle
                else len(noodles) == 1
            ),
        }
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            failures.append(f"{name}: {', '.join(failed_checks)}")
        validations.append(
            {
                "common_name": name,
                "cochlea_file": str(cochlea_path),
                "noodle_file": str(noodle_path),
                "checks": checks,
                "cochlea_dimensions": vector_tuple(cochlea_dimensions),
                "noodle_dimensions": vector_tuple(noodle_dimensions),
                "pair_center_distance": round(center_distance, 8),
                "cochlea_materials": cochlea_materials,
                "noodle_materials": noodle_materials,
                "noodle_meshes": len(noodles),
                "noodle_mesh_names": sorted(noodle.name for noodle in noodles),
                "cochlea_opening": cochlea_opening,
            }
        )

    output = {
        "source_report": str(args.report.resolve()),
        "pair_count": len(validations),
        "file_count": len(validations) * 2,
        "passed": not failures,
        "failures": failures,
        "records": validations,
    }
    args.validation.resolve().write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: output[key] for key in ("pair_count", "file_count", "passed", "failures")}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

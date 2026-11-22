"""Remove the planar fins attached to the already joined Nailoong surface."""

import json
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, sifu


def surface_signature(face, uv_layer, weight_layer):
    return (
        face.material_index,
        face.smooth,
        tuple(
            (tuple(loop.vert.co), tuple(loop[uv_layer].uv), tuple(sorted(loop.vert[weight_layer].items())))
            for loop in face.loops
        ),
    )


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = bpy.data.objects["Armature"]
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    try:
        bm.normal_update()
        uv = bm.loops.layers.uv["NailoongAtlas"]
        weights = bm.verts.layers.deform.active
        # In the fitted model the centre plane is offset by a fraction of a mm.
        fins = {
            face for face in bm.faces
            if all(abs(v.co.x + .0044) < .002 for v in face.verts) and abs(face.normal.x) > .99
        }
        if not fins:
            raise RuntimeError("Expected a planar centre fin in the v3 mesh")
        fin_edges = {e for face in fins for e in face.edges}
        roots = {e for e in fin_edges if any(face not in fins for face in e.link_faces)}
        for edge in roots:
            exterior = [face for face in edge.link_faces if face not in fins]
            if len(exterior) != 2:
                raise RuntimeError("Fin removal would leave an opening in the outer skin")
            left, right = [f.calc_center_median().x for f in exterior]
            if (left + .0044) * (right + .0044) >= 0:
                raise RuntimeError("Expected exterior faces on both sides of the centre")
        exterior = {face: surface_signature(face, uv, weights) for face in bm.faces if face not in fins}
        surviving_borders = {e for e in bm.edges if e.is_boundary and e not in fin_edges}
        count = {"vertices": len(bm.verts), "faces": len(bm.faces),
                 "open_edges": sum(e.is_boundary for e in bm.edges)}
        bmesh.ops.delete(bm, geom=list(fins), context="FACES")
        bm.normal_update()
        if set(bm.faces) != exterior.keys() or any(surface_signature(f, uv, weights) != signature
                                                  for f, signature in exterior.items()):
            raise RuntimeError("The original exterior geometry, UV or skin weights changed")
        if {e for e in bm.edges if e.is_boundary} != surviving_borders:
            raise RuntimeError("The edit changed a boundary outside the fins")
        if not all(e.is_manifold and e.smooth for e in roots):
            raise RuntimeError("The centre remains split or has a hard edge")
        bm.to_mesh(mesh.data)
        mesh.data.update()
        report = {
            "before": count,
            "after": {"vertices": len(bm.verts), "faces": len(bm.faces),
                      "open_edges": len(surviving_borders)},
            "removed_planar_faces": len(fins),
            "repaired_smooth_edges": len(roots),
            "verified_exterior_faces": len(exterior),
        }
    finally:
        bm.free()

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-Seamless.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-seam-fix.fbx"), [arm, mesh])
    (OUT / "center-seam-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

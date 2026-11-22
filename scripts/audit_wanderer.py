"""Verify the outfit against the v14 rig and render the fit in original game poses."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, SKELETON, sifu
from build_wanderer import WORK
from fit_idle_arms import frames
from preview_model import pose
from smooth_neck import IDLE, MOTION


def surface(obj, graph):
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    tree = BVHTree.FromPolygons([v.co for v in mesh.vertices], triangles, all_triangles=True)
    evaluated.to_mesh_clear()
    return tree, len(triangles)


def cameras():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.background_type = "WORLD"
    scene.world = bpy.data.worlds.new("Preview background")
    scene.world.color = (.10, .10, .10)
    scene.render.resolution_x = 660
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    camera = bpy.data.objects.new("Fit preview", bpy.data.cameras.new("Fit preview"))
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 225
    camera.data.clip_end = 2000
    scene.collection.objects.link(camera)
    scene.camera = camera
    return camera


def render(camera, name, rest):
    output = WORK / "previews"
    output.mkdir(exist_ok=True)
    views = {"front": (0, -355, 115), "side": (-350, 0, 104), "back": (0, 355, 119),
             "quarter": (190, -310, 130)} if rest else {"quarter": (225, -300, 127), "rear": (-215, 305, 132)}
    target = Vector((0, 0, 99))
    for view, loc in views.items():
        camera.location = loc
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.render.filepath = str(output / f"{name}-{view}.png")
        bpy.ops.render.render(write_still=True)


def rig_roundtrip():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sifu.setup_cm_scene()
    bpy.ops.import_scene.fbx(filepath=str(WORK / "SK_Nailoong_Wanderer.fbx"), use_anim=False,
                             automatic_bone_orientation=False, use_prepost_rot=True)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    expected = {n: sifu.ue_to_bl(m) for n, m in sifu.ue_world(sifu.load_skel(str(SKELETON))).items()}
    errors = []
    for n, matrix in expected.items():
        actual = arm.matrix_world @ arm.data.bones[n].matrix_local
        errors.extend(abs(actual[i][j] - matrix[i][j]) for i in range(4) for j in range(4))
    assert len(arm.data.bones) == len(expected) == 273 and max(errors) < .005
    slots = set()
    for obj in (o for o in bpy.data.objects if o.type == "MESH"):
        slots.update(slot.name for slot in obj.material_slots)
        assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
                   for v in obj.data.vertices), obj.name
    assert slots == {"M_Nailoong", "M_Nailoong_Wanderer"}, slots
    return {"bones": 273, "bind_matrix_max_error": max(errors), "slots": sorted(slots)}


def main():
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "Nailoong-RoundBack.blend"), load_ui=False)
    original = np.array([tuple(v.co) for v in bpy.data.objects["SK_Nailoong"].data.vertices])
    bpy.ops.wm.open_mainfile(filepath=str(WORK / "Nailoong-Wanderer.blend"), load_ui=False)
    arm = bpy.data.objects["Armature"]
    body = bpy.data.objects["SK_Nailoong"]
    assert np.array_equal(original, np.array([tuple(v.co) for v in body.data.vertices]))
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and o != body]
    clips = [*frames(ROOT / "local/animation-audit", MOTION), *frames(ROOT / "local/idle-audit", IDLE)]
    assert {clip[0] for clip in clips} == MOTION | IDLE
    samples = [("Rest", None, None), *clips]
    camera = cameras()
    rows = []
    for name, frame, refs in samples:
        pose(arm, frame, refs)
        graph = bpy.context.evaluated_depsgraph_get()
        body_tree, _ = surface(body, graph)
        overlaps = {}
        for part in parts:
            tree, count = surface(part, graph)
            overlaps[part.name] = {"overlapping_triangles": len({j for _, j in body_tree.overlap(tree)}),
                                   "total_triangles": count}
        rows.append({"clip": name, "frame": frame["frame"] if frame else None, "body_intersections": overlaps})
    for name in sorted({i[0] for i in samples}):
        selected = [row for row in samples if row[0] == name]
        label, frame, refs = selected[len(selected) // 2]
        pose(arm, frame, refs)
        title = label if frame is None else f"{label}-{frame['frame']}"
        render(camera, title, frame is None)
    report = {"body_mesh_positions_match_v14": True, "fbx_roundtrip": rig_roundtrip(), "samples": rows}
    (WORK / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"OUTFIT_AUDIT_OK {len(samples)} poses")


if __name__ == "__main__":
    main()

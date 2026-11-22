"""Audit bind matrices, influences, FBX round trip and sampled limb deformation."""
import argparse
import json
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_model import SKELETON, sifu, arm_regions
from preview_model import pose

bpy.ops.wm.open_mainfile(filepath=str(ROOT / "source/nailoong/nailong_colored.blend"), load_ui=False)
source_mesh = next(o.data for o in bpy.context.scene.objects if o.type == "MESH")
COMMON_ARM_VERTICES = {i for i, a in enumerate(arm_regions(source_mesh)) if a > .95}


def inspect(path, check_reference):
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    arm = bpy.data.objects["Armature"]
    obj = bpy.data.objects["SK_Nailoong"]
    if not check_reference:
        obj.modifiers["Sifu skeleton"].use_deform_preserve_volume = False
    bones = sifu.load_skel(str(SKELETON))
    expected = {n: sifu.ue_to_bl(m) for n, m in sifu.ue_world(bones).items()}
    worst = max(max(abs(arm.data.bones[n].matrix_local[i][j] - m[i][j]) for i in range(4) for j in range(4))
                for n, m in expected.items())
    sums = [sum(g.weight for g in v.groups) for v in obj.data.vertices]
    counts = [len(v.groups) for v in obj.data.vertices]
    assert min(sums) > .9999 and max(sums) < 1.0001
    assert max(counts) <= 4
    if check_reference:
        assert worst < .001, worst
        for b in bones:
            parent = arm.data.bones[b["name"]].parent
            assert (parent.name if parent else None) == (bones[b["parent"]]["name"] if b["parent"] >= 0 else None)
        assert not obj.modifiers["Sifu skeleton"].use_deform_preserve_volume
    positions = np.array([tuple(v.co) for v in obj.data.vertices])
    names = {g.index: g.name for g in obj.vertex_groups}
    arm_vertices = COMMON_ARM_VERTICES
    edges = np.array([tuple(e.vertices) for e in obj.data.edges if all(i in arm_vertices for i in e.vertices)])
    base_lengths = np.linalg.norm(positions[edges[:, 0]] - positions[edges[:, 1]], axis=1)
    good = base_lengths > .01
    edges, base_lengths = edges[good], base_lengths[good]
    samples = []
    for clip in sorted((ROOT / "local/animation-audit").glob("*.anim.json")):
        data = json.loads(clip.read_text())
        refs = {b["name"]: b for b in data["reference"]}
        for frame in data["frames"]:
            pose(arm, frame, refs)
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            points = np.array([tuple(v.co) for v in mesh.vertices])
            assert np.isfinite(points).all()
            lengths = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
            ratio = lengths / base_lengths
            samples.append({"clip": data["name"], "frame": frame["frame"],
                            "arm_edge_stretch_p99": float(np.percentile(ratio, 99)),
                            "arm_edge_stretch_max": float(ratio.max()),
                            "arm_edge_ratio_p01": float(np.percentile(ratio, 1))})
            evaluated.to_mesh_clear()
    return {"bind_matrix_max_error": worst, "vertices": len(positions), "bone_count": len(arm.data.bones),
            "max_influences": max(counts), "weight_sum_range": [min(sums), max(sums)],
            "sample_count": len(samples), "samples": samples}


parser = argparse.ArgumentParser()
parser.add_argument("--before", type=Path, default=ROOT / "build/backups/before-arm-fix-20261115/model/Nailoong-Sifu.blend")
parser.add_argument("--after", type=Path, default=ROOT / "build/model/Nailoong-Sifu.blend")
parser.add_argument("--fbx", type=Path, default=ROOT / "build/model/SK_Nailoong.fbx")
parser.add_argument("--output", type=Path, default=ROOT / "build/arm-fix/validation.json")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
before = inspect(ROOT / args.before, False)
after = inspect(ROOT / args.after, True)
# The importer must recover exactly the same reference matrices in scene cm.
bpy.ops.wm.read_factory_settings(use_empty=True)
sifu.setup_cm_scene()
bpy.ops.import_scene.fbx(filepath=str(ROOT / args.fbx), use_anim=False,
                         automatic_bone_orientation=False, use_prepost_rot=True)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
expected = {n: sifu.ue_to_bl(m) for n, m in sifu.ue_world(sifu.load_skel(str(SKELETON))).items()}
error = max(max(abs((arm.matrix_world @ arm.data.bones[n].matrix_local)[i][j] - m[i][j])
                for i in range(4) for j in range(4)) for n, m in expected.items())
assert error < .005, ("FBX reference mismatch", error)
out = ROOT / args.output
out.parent.mkdir(exist_ok=True, parents=True)
out.write_text(json.dumps({"before": before, "after": after, "fbx_bind_matrix_max_error": error}, indent=2))
print("RIG_AUDIT_OK", "FBX error", error, "sampled poses", after["sample_count"])

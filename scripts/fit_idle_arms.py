"""Give the v5 mesh elbow and hand clearance in the original barehanded idle."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from preview_model import pose
from shorten_leg_silhouette import coordinates, influence, set_coordinates, smooth


def frames(directory, names):
    for path in sorted(directory.glob("*.anim.json")):
        clip = json.loads(path.read_text(encoding="utf-8"))
        if clip["name"] not in names:
            continue
        reference = {bone["name"]: bone for bone in clip["reference"]}
        for frame in clip["frames"]:
            yield clip["name"], frame, reference


def shape(base, arm_weight, torso_weight, arm_offset, flank_depth, elbow_offset, grip=False):
    points = base.copy()
    x, y, z = base.T
    side = np.sign(x)
    # Reduce lateral volume around wrist height, leaving the rounded front
    # of the belly and the pelvis/legs in place.
    waist = smooth(76, 96, z) * (1 - smooth(117, 143, z))
    flank = 1 - smooth(13, 33, np.abs(y - 1))
    torso = smooth(.58, .995, torso_weight) * waist * flank
    flank_profile = x / 34 if grip else side * smooth(3, 32, np.abs(x))
    points[:, 0] -= flank_depth * torso * flank_profile

    # Taper the rest mesh adjustment from the hand to its shoulder attachment.
    # Lateral space comes mostly from the forearm, without changing bone axes.
    lower = 1 - smooth(101, 147, z)
    elbow = smooth(103, 119, z) * (1 - smooth(123, 147, z))
    limb = smooth(.05, .99, arm_weight)
    points[:, 0] += side * limb * (arm_offset * lower + elbow_offset * elbow)
    return points


def clearance(mesh, arm, clips, points, torso, hands, forearm):
    set_coordinates(mesh.data, points)
    outer_faces = [tuple(poly.vertices) for poly in mesh.data.polygons if all(torso[i] for i in poly.vertices)]
    result = []
    found = set()
    for name, frame, reference in clips:
        found.add(name)
        pose(arm, frame, reference)
        xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
        tree = BVHTree.FromPolygons(xyz.tolist(), outer_faces)
        measures = {}
        for side, hand_zone, arm_zone in zip((1, -1), hands, forearm):
            direction = Vector((-side, 0, 0))
            for label, zone in (("palm", hand_zone), ("forearm", arm_zone)):
                margins = []
                for x, y, z in xyz[zone]:
                    hit = tree.ray_cast(Vector((side * 100, y, z)), direction)[0]
                    if hit and hit.x * side > 0:
                        margins.append(float((x - hit.x) * side))
                margins = np.asarray(margins)
                measures[f"{label}_{'l' if side > 0 else 'r'}"] = {
                    "minimum_cm": float(margins.min()) if len(margins) else None,
                    "contact_fraction": float(np.count_nonzero(margins < -.15) / (len(margins) or 1)),
                }
        result.append({"clip": name, "frame": frame["frame"], "clearance": measures})
    if found != {"MC_man_barehands_V0_front", "MC_man_barehands_V0_front_pose"}:
        raise RuntimeError("Both idle references are required")
    return result


def worst(records, region):
    return max(record["clearance"][f"{region}_{side}"]["contact_fraction"]
               for record in records for side in ("l", "r"))


def palm_margin(records):
    distances = (record["clearance"][f"palm_{side}"]["minimum_cm"]
                 for record in records for side in ("l", "r"))
    return min(distance for distance in distances if distance is not None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grip", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = bpy.data.objects["Armature"]
    base = coordinates(mesh.data)
    arm_weight = influence(mesh, ("upperarm", "lowerarm", "hand_"))
    torso_weight = influence(mesh, ("spine_", "pelvis"))
    # The torso occludes the fingertips in idle. Include the hip surface as
    # well, while excluding arms, to estimate side clearance in motion.
    torso_faces = (arm_weight < .18) & (base[:, 2] > 56)
    hands = tuple(influence(mesh, (f"hand_{side}",)) > .92 for side in ("l", "r"))
    forearms = tuple((base[:, 2] < 122) & (base[:, 0] * sign > 0) &
                     (influence(mesh, ("lowerarm_",)) > .94) for sign in (1, -1))
    clips = list(frames(ROOT / "local/idle-audit", {"MC_man_barehands_V0_front", "MC_man_barehands_V0_front_pose"}))
    baseline = clearance(mesh, arm, clips, base, torso_faces, hands, forearms)
    best = None
    options = ((8, 8, 0), (10, 8, 0), (10, 8, 2), (10, 9, 2), (11, 9, 0), (11, 9, 2), (12, 9, 0))
    if args.grip:
        options = ((7, 16, 3), (7, 17, 3), (8, 13, 3), (8, 14, 3), (9, 11, 3), (10, 9, 2))
    for arm_offset, flank_depth, elbow_offset in options:
        revised = shape(base, arm_weight, torso_weight, arm_offset, flank_depth, elbow_offset, grip=args.grip)
        samples = clearance(mesh, arm, clips, revised, torso_faces, hands, forearms)
        palm, forearm = worst(samples, "palm"), worst(samples, "forearm")
        margin = palm_margin(samples)
        if args.grip and (palm > 0 or forearm > .03 or margin < .5):
            print(f"Arm {arm_offset}, flank {flank_depth}: rejected, palm gap {margin:.2f} cm", flush=True)
            continue
        merit = (max(0, palm - .008) * 30 + max(0, forearm - .015) * 14
                 + max(0, .6 - margin) * 3
                 + (1.5 if args.grip else .7) * arm_offset + .3 * flank_depth + .1 * elbow_offset)
        print(f"Arm {arm_offset}, flank {flank_depth}, elbow {elbow_offset}: palm {palm:.2%}, "
              f"forearm {forearm:.2%}, palm gap {margin:.2f} cm", flush=True)
        if best is None or merit < best[0]:
            best = merit, arm_offset, flank_depth, elbow_offset, revised, samples
    _, arm_offset, flank_depth, elbow_offset, revised, samples = best
    if worst(samples, "palm") > .008 or worst(samples, "forearm") > .04 or palm_margin(samples) < .4:
        raise RuntimeError("The arm edit still has visible overlap in the idle sample")
    joints = {b.name: b.bone.matrix_local.copy() for b in arm.pose.bones}
    assert np.array_equal(base[base[:, 2] < 76], revised[base[:, 2] < 76])
    assert np.array_equal(base[base[:, 2] > 147], revised[base[:, 2] > 147])
    assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices)
    set_coordinates(mesh.data, revised)
    pose(arm, None)
    assert all(b.bone.matrix_local == joints[b.name] for b in arm.pose.bones)
    bpy.context.preferences.filepaths.save_version = 0
    project = "Nailoong-Grip" if args.grip else "Nailoong-IdleArms"
    tag = "grip" if args.grip else "idle-arms"
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / f"{project}.blend"))
    sifu.export_fbx(str(OUT / f"SK_Nailoong-{tag}.fbx"), [arm, mesh])
    report = {"arm_offset_cm": arm_offset, "maximum_flank_reduction_cm": flank_depth,
              "elbow_offset_cm": elbow_offset,
              "v5": baseline, "revised": samples}
    (OUT / f"{tag}-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Selected arm {arm_offset}, flank {flank_depth}, elbow {elbow_offset}")


if __name__ == "__main__":
    main()

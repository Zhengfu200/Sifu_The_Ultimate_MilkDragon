"""Fit the mesh-only weapon sockets to the v6 palms in original weapon poses."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import ROOT
from preview_model import pose
from shorten_leg_silhouette import coordinates, influence


def read_samples(mesh, arm):
    # Use the rigid palm members so the fit is independent of the wrist blend.
    masks = {side: influence(mesh, (f"hand_{side}",)) > .99 for side in ("l", "r")}
    samples = []
    paths = sorted((ROOT / "local/grip-pose-audit").glob("*.anim.json"))
    paths.extend(sorted((ROOT / "local/animation-audit").glob("*Staff_Guard*.anim.json")))
    for path in paths:
        if not any(family in path.name.lower() for family in ("bats", "blades", "staff")):
            continue
        clip = json.loads(path.read_text(encoding="utf-8"))
        dual = "staff" in clip["name"].lower()
        reference = {b["name"]: b for b in clip["reference"]}
        for frame in clip["frames"]:
            pose(arm, frame, reference)
            xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
            points = {side: np.median(xyz[mask], axis=0) for side, mask in masks.items()}
            right = np.array(arm.pose.bones["weapon_r"].matrix.inverted())
            # Both reference props run along local Y. For the shaft fit, ignore
            # movement along Y, but keep the pipe's longitudinal grip location.
            transformed = {side: (right[:3, :3] @ point + right[:3, 3])
                           for side, point in points.items()}
            anchors = {side: np.array(arm.pose.bones[f"weapon_{side}"].head) for side in masks}
            left_anchor = right[:3, :3] @ anchors["l"] + right[:3, 3]
            left_on_shaft = dual and np.linalg.norm(left_anchor[[0, 2]]) < 5
            samples.append({"clip": clip["name"], "frame": frame["frame"], "two_handed": dual,
                            "left_on_shaft": bool(left_on_shaft), "palms": transformed})
    pose(arm, None)
    return samples


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    samples = read_samples(mesh, arm)
    equipped = [s for s in samples if "move_v0" in s["clip"].lower()]
    pipe = [s for s in equipped if "bats" in s["clip"]]
    staff_guard = [s for s in samples if s["left_on_shaft"] and "Guard" in s["clip"]]
    if not pipe or not staff_guard:
        raise RuntimeError("Expected equipped and two-handed guard clips")
    # Favor conventional single-hand holds. Compare the shared shaft in the
    # guard separately because that pose pins both palms to the same object.
    center = np.median([s["palms"]["r"] for s in equipped], axis=0)
    center[1] = np.median([s["palms"]["r"][1] for s in pipe])
    # The retargeted left weapon bone is usually released in these clips. Mirror
    # the correction in the two bones' reference bases for a left-hand attach.
    right_basis = np.array(arm.data.bones["weapon_r"].matrix_local.to_3x3())
    left_basis = np.array(arm.data.bones["weapon_l"].matrix_local.to_3x3())
    left = np.linalg.inv(left_basis) @ (np.diag((-1, 1, 1)) @ right_basis @ center)
    skeleton = ROOT / "local/grip-audit/Sifu/Content/Characters/Skeleton/Base_skeleton.json"
    properties = {e["Properties"]["SocketName"]: e["Properties"] for e in json.loads(skeleton.read_text())
                  if e["Type"] == "SkeletalMeshSocket"}
    spec = []
    for side, bl_location in (("l", left), ("r", center)):
        engine_location = [float(v) for v in bl_location * np.array([1, -1, 1])]
        bone = f"weapon_{side}"
        original = properties[f"{bone}_object"]
        orig_location = original.get("RelativeLocation", {})
        orig_rotation = original.get("RelativeRotation", {})
        spec.extend([
            {"name": bone, "bone": bone, "position": engine_location, "rotation": [0, 0, 0]},
            {"name": f"{bone}_object", "bone": bone,
             "position": [engine_location[i] + orig_location.get(axis, 0) for i, axis in enumerate("XYZ")],
             "rotation": [orig_rotation.get(axis, 0) for axis in ("Pitch", "Yaw", "Roll")]},
        ])
    datasets = {
        "pipe_right_hand": [s["palms"]["r"] for s in pipe],
        "blade_right_hand": [s["palms"]["r"] for s in equipped if "blades" in s["clip"].lower()],
        "staff_right_hand_equipped": [s["palms"]["r"] for s in equipped if s["two_handed"]],
        "staff_guard_right": [s["palms"]["r"] for s in staff_guard],
        "staff_guard_left": [s["palms"]["l"] for s in staff_guard],
    }
    report = {}
    for name, values in datasets.items():
        transverse = np.asarray(values)[:, [0, 2]]
        before = np.linalg.norm(transverse, axis=1)
        after = np.linalg.norm(transverse - center[[0, 2]], axis=1)
        if "guard" not in name and float(np.median(after)) >= float(np.median(before)):
            raise RuntimeError(f"Socket adjustment did not improve grip for {name}")
        report[name] = {"sample_count": len(values), "median_before_cm": float(np.median(before)),
                        "median_after_cm": float(np.median(after)), "max_after_cm": float(after.max())}
    output = ROOT / "build/grip-fix"
    output.mkdir(exist_ok=True)
    (output / "sockets.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"right_socket_ue_cm": spec[2]["position"], **report}, indent=2))


if __name__ == "__main__":
    main()

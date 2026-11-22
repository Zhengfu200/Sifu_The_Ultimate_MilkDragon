"""Refit the v10 lower-body silhouette around the unchanged game skeleton."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from fit_idle_arms import frames
from preview_model import pose
from round_belly import snapshot
from shorten_leg_silhouette import coordinates, influence, set_coordinates, set_weights, smooth


MOTIONS = {
    "MC_man_barehands_V3_north",
    "MC_man_attack_bats_Light_PushKick_FR",
    "MC_man_barehands_knockDown_dodge_east",
}
IDLES = {"MC_man_barehands_V0_front", "MC_man_barehands_V0_front_pose"}


def sculpt(base, edges, freedom, legs, depth, bulk):
    x, y, z = base.T
    hip = smooth(13, 73, z) * (1 - smooth(75, 104, z))
    inner = 1 - smooth(5, 24, np.abs(x))
    radius_z = (12, 20, 34, 47, 59, 71)
    center_x = np.interp(z, radius_z, (15.4, 14.9, 13.6, 13.1, 14.0, 15.3))
    center_y = np.interp(z, radius_z, (3.4, 2.6, 1.6, 1.1, 1.4, 2.6))
    radius_x = np.interp(z, radius_z, (5.9, 7.2, 8.9, 10.1, 11.2, 13.3))
    radius_y = np.interp(z, radius_z, (5.1, 6.4, 8.4, 10.3, 12.6, 13.2))
    angle = np.arctan2((y - center_y) / radius_y, (np.abs(x) - center_x) / radius_x)
    rounded_x = np.sign(x) * (center_x + radius_x * np.cos(angle))
    rounded_y = center_y + radius_y * np.sin(angle)
    roundness = bulk * smooth(10, 24, z) * (1 - smooth(54, 73, z)) * legs * freedom
    result = base.copy()
    result[:, 0] += (rounded_x - x) * roundness
    result[:, 1] += (rounded_y - y) * roundness
    result[:, 2] -= depth * hip * (.80 + .20 * inner) * freedom

    # Fair the knee and ankle outline after reshaping without shrinking the soles.
    region = smooth(12, 20, z) * (1 - smooth(67, 96, z)) * freedom
    a, b = edges[(region[edges] > 0).any(axis=1)].T
    start, end = np.r_[a, b], np.r_[b, a]
    degree = np.bincount(start, minlength=len(base)).clip(min=1)[:, None]
    for _ in range(20):
        for step in (.45, -.39):
            average = np.zeros_like(result)
            np.add.at(average, start, result[end])
            result += step * region[:, None] * (average / degree - result)
    return result


def weight_candidates(original, base, freedom, edges):
    # Diffuse the pelvis, thigh and calf transitions along the connected shell.
    # The feet and lower abdomen anchor the two ends of the edited region.
    z = base[:, 2]
    strength = freedom * smooth(21, 38, z) * (1 - smooth(76, 93, z))
    ids = np.flatnonzero(strength > 1e-6)
    patch = edges[(strength[edges] > 1e-6).any(axis=1)]
    a, b = patch.T
    start, end = np.r_[a, b], np.r_[b, a]
    neighbours = set(np.r_[ids, end])
    groups = np.array(sorted({g for i in neighbours for g in original[i]}))
    columns = {g: i for i, g in enumerate(groups)}
    weights = np.zeros((len(base), len(groups)), dtype=np.float32)
    for i in neighbours:
        for group, weight in original[i].items():
            weights[i, columns[group]] = weight
    counts = np.bincount(start, minlength=len(base)).clip(min=1)[:, None]
    yield 0, ids, groups, weights[ids]
    for step in range(1, 97):
        average = np.zeros_like(weights)
        np.add.at(average, start, weights[end])
        weights[ids] += .6 * strength[ids, None] * (average[ids] / counts[ids] - weights[ids])
        if step in (24, 56, 96):
            rows = weights[ids]
            columns = np.argsort(rows, axis=1)[:, -4:]
            limited = np.zeros_like(rows)
            np.put_along_axis(limited, columns, np.take_along_axis(rows, columns, axis=1), axis=1)
            limited[limited < 1e-5] = 0
            limited /= limited.sum(axis=1, keepdims=True)
            yield step, ids, groups, limited


def measure(mesh, arm, samples, points, tracked, faces, fixed):
    set_coordinates(mesh.data, points)
    rest_lengths = np.linalg.norm(points[tracked[:, 0]] - points[tracked[:, 1]], axis=1)
    if np.any(rest_lengths < .02):
        raise RuntimeError("Collapsed edge in the lower-body rest mesh")
    records, anchors = [], []
    for name, frame, references in samples:
        pose(arm, frame, references)
        xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
        posed = np.linalg.norm(xyz[tracked[:, 0]] - xyz[tracked[:, 1]], axis=1)
        low, high = np.percentile(posed / rest_lengths, (1, 99))
        verts = xyz.tolist()
        left, right = (BVHTree.FromPolygons(verts, side) for side in faces)
        pairs = left.overlap(right)
        contacts = len({i for i, _ in pairs}) + len({j for _, j in pairs})
        records.append({"clip": name, "frame": frame["frame"], "compression_p01": float(low),
                        "stretch_p99": float(high), "overlapping_leg_faces": contacts})
        anchors.append(xyz[fixed])
    return records, np.array(anchors)


def motion_metrics(records):
    return {
        "stretch": max(row["stretch_p99"] for row in records),
        "compression": min(row["compression_p01"] for row in records),
        "peak_contact": max(row["overlapping_leg_faces"] for row in records),
        "contact_frames": sum(row["overlapping_leg_faces"] > 0 for row in records),
    }


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    base = coordinates(mesh.data)
    x, _, z = base.T
    foot = influence(mesh, ("foot_", "ball_"))
    legs = influence(mesh, ("thigh_", "calf_"))
    arms = influence(mesh, ("clavicle_", "upperarm", "lowerarm", "hand_"))
    freedom = (1 - smooth(.02, .25, arms)) * (1 - smooth(.06, .80, foot)) * smooth(10, 23, z)
    fixed = (z <= 10) | (z >= 104) | (arms >= .25) | (foot >= .80)
    edges = np.array([tuple(edge.vertices) for edge in mesh.data.edges])
    tracked = edges[((z > 12) & (z < 90) & (arms < .02))[edges].all(axis=1)]
    tracked = tracked[np.linalg.norm(base[tracked[:, 0]] - base[tracked[:, 1]], axis=1) > .10]
    faces = []
    for sign in (1, -1):
        side = (x * sign > .1) & (legs + foot > .65) & (z < 56)
        faces.append([tuple(poly.vertices) for poly in mesh.data.polygons if side[list(poly.vertices)].all()])
    samples = list(frames(ROOT / "local/animation-audit", MOTIONS)) + list(frames(ROOT / "local/idle-audit", IDLES))
    if {name for name, _, _ in samples} != MOTIONS | IDLES or len(tracked) < 1000 or not all(faces):
        raise RuntimeError("Missing original leg poses or leg surface")
    original = snapshot(mesh)
    joints = {b.name: b.matrix_local.copy() for b in arm.data.bones}
    initial, anchors = measure(mesh, arm, samples, base, tracked, faces, fixed)
    baseline = motion_metrics(initial)
    print("v10:", baseline, flush=True)
    weights = tuple(weight_candidates(original, base, freedom, edges))
    best = None
    for depth, bulk in ((16, .78), (18, .85), (20, .85), (21, .92)):
        revised = sculpt(base, edges, freedom, legs, depth, bulk)
        if not np.array_equal(base[fixed], revised[fixed]):
            raise RuntimeError("The sculpt moved vertices outside the leg and hip region")
        for candidate in weights:
            set_weights(mesh, candidate)
            tested, protected = measure(mesh, arm, samples, revised, tracked, faces, fixed)
            if not np.array_equal(anchors, protected):
                raise RuntimeError("The new shape shifted the animated soles or upper body")
            result = motion_metrics(tested)
            print(depth, bulk, candidate[0], result, flush=True)
            # Compare with the v10 motion envelope before preferring more shortening.
            merit = (result["stretch"] - baseline["stretch"]
                     + 2 * (baseline["compression"] - result["compression"])
                     + .015 * max(0, result["peak_contact"] - baseline["peak_contact"])
                     + .05 * max(0, result["contact_frames"] - baseline["contact_frames"])
                     - .12 * depth - .4 * bulk)
            if result["stretch"] <= baseline["stretch"] and (best is None or merit < best[0]):
                best = merit, depth, bulk, candidate, revised, tested

    if best is None:
        raise RuntimeError("No shortened shape stayed within the v10 peak stretch")
    _, depth, bulk, candidate, revised, tested = best
    set_coordinates(mesh.data, revised)
    set_weights(mesh, candidate)
    assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices)
    assert all(b.matrix_local == joints[b.name] for b in arm.data.bones)
    pose(arm, None)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-CompactLegs.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-compact-legs.fbx"), [arm, mesh])
    middle = np.abs(x) < .15
    report = {
        "source": "Nailoong-SmoothNeck.blend",
        "hip_drop_cm": depth,
        "leg_bulk": bulk,
        "lower_body_weight_smoothing_passes": candidate[0],
        "standing_inseam_cm_before": float(z[middle].min() - z.min()),
        "standing_inseam_cm_after": float(revised[middle, 2].min() - z.min()),
        "maximum_animated_protected_vertex_shift_cm": 0,
        "motion_before": baseline,
        "motion_after": motion_metrics(tested),
        "before": initial,
        "after": tested,
    }
    (OUT / "compact-legs-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({k: v for k, v in report.items() if k not in ("before", "after")})


if __name__ == "__main__":
    main()

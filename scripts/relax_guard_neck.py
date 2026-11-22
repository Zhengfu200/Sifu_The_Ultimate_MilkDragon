"""Reduce the throat and upper-chest fold visible in the guard pose."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blend_shoulders import adjacency, fold_angles, hinges_in_patch
from build_model import OUT, ROOT, sifu
from fit_idle_arms import frames
from preview_model import pose
from refine_arm_weights import limited
from round_belly import snapshot
from shorten_leg_silhouette import coordinates, influence, set_coordinates, set_weights, smooth
from smooth_neck import IDLE, MOTION, UPPER_BODY


DEFENSE = "MC_man_Staff_Guard_FR"


def smooth_throat(base, edges, region, depth):
    x, y, z = base.T
    points = base.copy()
    # Ease the added volume below the jaw, with fixed anchors at the chin
    # and chest so this does not create a second lip above the first one.
    points[:, 1] += depth * smooth(134, 148, z) * (1 - smooth(152, 161, z)) * region
    fair = region * smooth(130, 142, z) * (1 - smooth(154, 162, z))
    start, end, degree = adjacency(edges, fair)
    for _ in range(28):
        for step in (.52, -.3):
            average = np.zeros_like(points)
            np.add.at(average, start, points[end])
            points += step * fair[:, None] * (average / degree - points)
    return points


def torso_weights(mesh, points, region):
    original = snapshot(mesh)
    ids = np.flatnonzero(region)
    chain = [mesh.vertex_groups[name].index for name in UPPER_BODY]
    groups = np.array(chain + sorted({g for i in ids for g in original[i]} - set(chain)))
    count = len(chain)
    old = np.array([[original[i].get(group, 0) for group in groups] for i in ids], dtype=np.float32)
    z = points[ids, 2]
    yield "original", ids, groups, old
    for bands in (
        ((117, 141), (122, 148), (134, 153), (140, 158), (146, 162)),
        ((118, 145), (122, 150), (132, 154), (136, 157), (144, 162)),
        ((120, 145), (122, 150), (137, 155), (141, 159), (148, 162)),
        ((119, 141), (121, 147), (137, 156), (144, 160), (149, 162)),
        ((118, 140), (122, 145), (140, 156), (142, 160), (147, 162)),
    ):
        levels = [np.ones(len(z)), *(smooth(low, high, z) for low, high in bands), np.zeros(len(z))]
        profile = np.stack([start - end for start, end in zip(levels, levels[1:])], axis=1)
        mix = region[ids, None]
        weights = old.copy()
        band = weights[:, :count]
        band[:] = (1 - mix) * band + profile * mix * band.sum(axis=1, keepdims=True)
        yield bands, ids, groups, limited(weights)


def measure(mesh, arm, samples, points, triangles, tracked, hinges, fixed):
    set_coordinates(mesh.data, points)
    a, b = tracked.T
    length = np.linalg.norm(points[a] - points[b], axis=1)
    if np.any(length < .02):
        raise RuntimeError("Collapsed edge in the throat surface")
    rows, anchors = [], []
    for name, frame, reference in samples:
        pose(arm, frame, reference)
        xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
        strain = np.linalg.norm(xyz[a] - xyz[b], axis=1) / length
        low, high = np.percentile(strain, (5, 99))
        angle = fold_angles(xyz, triangles, hinges)
        rows.append({"clip": name, "frame": frame["frame"], "compression_p05": float(low),
                     "stretch_p99": float(high), "fold_p98_deg": float(np.percentile(angle, 98)),
                     "folds_over_90deg": int((angle > 90).sum())})
        anchors.append(xyz[fixed])
    return rows, np.array(anchors)


def summary(rows):
    return {
        "compression_p05_minimum": min(row["compression_p05"] for row in rows),
        "stretch_p99_peak": max(row["stretch_p99"] for row in rows),
        "fold_p98_mean": float(np.mean([row["fold_p98_deg"] for row in rows])),
        "folds_over_90_peak": max(row["folds_over_90deg"] for row in rows),
    }


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    base = coordinates(mesh.data)
    x, y, z = base.T
    limbs = influence(mesh, ("clavicle_", "upperarm", "lowerarm", "hand_"))
    freedom = (1 - smooth(11, 22, np.abs(x))) * (1 - smooth(.06, .25, limbs))
    front = 1 - smooth(-8, 8, y)
    region = freedom * front * smooth(114, 127, z) * (1 - smooth(155, 162, z))
    fixed = region == 0
    edges = np.array([tuple(edge.vertices) for edge in mesh.data.edges])
    measured = region * smooth(122, 128, z)
    triangles, tracked, hinges = hinges_in_patch(mesh.data, measured)
    length = np.linalg.norm(base[tracked[:, 0]] - base[tracked[:, 1]], axis=1)
    keep = (length > .09) & (z[tracked].max(axis=1) < 155)
    tracked, hinges = tracked[keep], hinges[keep]
    clips = list(frames(ROOT / "local/animation-audit", MOTION)) + list(frames(ROOT / "local/idle-audit", IDLE))
    if len(tracked) < 400 or {name for name, _, _ in clips} != MOTION | IDLE:
        raise RuntimeError("Missing neck surface or original guard and regression samples")
    original, anchors = measure(mesh, arm, clips, base, triangles, tracked, hinges, fixed)
    old_guard = summary([row for row in original if row["clip"] == DEFENSE])
    old_all = summary(original)
    print("v12 guard", old_guard, "all", old_all, flush=True)
    candidates = list(torso_weights(mesh, base, region))
    best = None
    for depth in (0, 1.35, 2.45):
        points = smooth_throat(base, edges, region, depth)
        for candidate in candidates:
            set_weights(mesh, candidate)
            rows, protected = measure(mesh, arm, clips, points, triangles, tracked, hinges, fixed)
            if not np.array_equal(anchors, protected):
                raise RuntimeError("The throat edit moved protected vertices in motion")
            guard = summary([row for row in rows if row["clip"] == DEFENSE])
            all_poses = summary(rows)
            print(depth, candidate[0], guard, all_poses, flush=True)
            score = (guard["fold_p98_mean"] * .16 + guard["folds_over_90_peak"] * .12
                     + 6 * (1 - guard["compression_p05_minimum"])
                     + 2 * guard["stretch_p99_peak"] + .06 * all_poses["fold_p98_mean"]
                     + 2 * all_poses["stretch_p99_peak"] + depth * .08)
            if (guard["fold_p98_mean"] < old_guard["fold_p98_mean"]
                    and all_poses["stretch_p99_peak"] < 1.08 * old_all["stretch_p99_peak"]
                    and (best is None or score < best[0])):
                best = score, depth, points, candidate, rows, guard, all_poses
    if best is None:
        raise RuntimeError("No throat revision improved the guard without excess stretch")
    _, depth, points, candidate, rows, guard, all_poses = best
    set_coordinates(mesh.data, points)
    set_weights(mesh, candidate)
    if not all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices):
        raise RuntimeError("Invalid skin weights")
    pose(arm, None)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-GuardNeck.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-guard-neck.fbx"), [arm, mesh])
    report = {"source": "Nailoong-SmoothShoulders.blend", "guard_clip": DEFENSE, "samples": len(rows),
              "neck_edges": len(tracked), "throat_depth_cm": depth, "weight_bands_cm": candidate[0],
              "max_rest_displacement_cm": float(np.linalg.norm(points - base, axis=1).max()),
              "guard_before": old_guard, "guard_after": guard, "all_before": old_all,
              "all_after": all_poses, "before": original, "after": rows}
    (OUT / "guard-neck-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({key: value for key, value in report.items() if key not in ("before", "after")})


if __name__ == "__main__":
    main()

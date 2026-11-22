"""Round the v11 shoulder folds and smooth their blend into the upper arms."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from fit_idle_arms import clearance, frames, palm_margin, worst
from preview_model import pose
from refine_arm_weights import limited
from shorten_leg_silhouette import coordinates, influence, set_coordinates, set_weights, smooth


IDLE = {"MC_man_barehands_V0_front", "MC_man_barehands_V0_front_pose"}
MOTION = {
    "MainChar_Attack_Man_Barehands_Pressure_ElbowMonoStrike_FL",
    "MainChar_Attack_Man_Barehands_Pressure_Jab_FR",
    "MC_man_attack_staff_Heavy_HeadMill_FL",
    "MC_man_barehands_knockDown_dodge_east",
    "MC_man_barehands_V3_north",
    "MC_man_Staff_Guard_FR",
}


def adjacency(edges, region):
    a, b = edges[(region[edges] > 0).any(axis=1)].T
    start, end = np.r_[a, b], np.r_[b, a]
    counts = np.bincount(start, minlength=len(region)).clip(min=1)[:, None]
    return start, end, counts


def smooth_shape(base, edges, region):
    start, end, counts = adjacency(edges, region)
    points = base.copy()
    for i in range(1, 101):
        # Allow some contraction so the overlapping underside of the old
        # shoulder lip can unfold. Keep the edges of the patch anchored.
        for step in (.54, -.23):
            average = np.zeros_like(points)
            np.add.at(average, start, points[end])
            points += step * region[:, None] * (average / counts - points)
        if i in (28, 58, 100):
            yield i, points.copy()


def weight_candidates(mesh, base, edges, region):
    names = [group.name for group in mesh.vertex_groups]
    patch = np.flatnonzero(region)
    start, end, counts = adjacency(edges, region)
    neighbors = np.unique(np.r_[patch, end])
    groups = {weight.group for i in neighbors for weight in mesh.data.vertices[int(i)].groups}
    groups.update(names.index(f"clavicle_{side}") for side in ("l", "r"))
    groups = np.array(sorted(groups))
    cols = {names[group]: i for i, group in enumerate(groups)}
    weights = np.zeros((len(base), len(groups)), dtype=np.float32)
    for i in neighbors:
        for assignment in mesh.data.vertices[int(i)].groups:
            weights[i, cols[names[assignment.group]]] = assignment.weight
    yield "original", patch, groups, weights[patch]

    x, _, z = base.T
    collar = smooth(12, 21, np.abs(x)) * smooth(128, 141, z) * region
    for collar_share in (0, .18):
        revised = weights.copy()
        if collar_share:
            for side, sign in (("l", 1), ("r", -1)):
                amount = collar * (x * sign > 0) * collar_share
                neck_cols = [cols[name] for name in ("neck_01", "neck_02") if name in cols]
                transfer = revised[:, neck_cols] * amount[:, None]
                revised[:, neck_cols] -= transfer
                revised[:, cols[f"clavicle_{side}"]] += transfer.sum(axis=1)
        for step in range(1, 13):
            average = np.zeros_like(revised)
            np.add.at(average, start, revised[end])
            revised[patch] += .58 * region[patch, None] * (average[patch] / counts[patch] - revised[patch])
            if step in (4, 12):
                yield f"{collar_share:.0%} clavicle, {step} passes", patch, groups, limited(revised[patch])


def fold_angles(points, triangles, hinges):
    tri = points[triangles]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normal /= np.linalg.norm(normal, axis=1, keepdims=True).clip(min=1e-10)
    cosine = np.einsum("ij,ij->i", normal[hinges[:, 0]], normal[hinges[:, 1]])
    return np.rad2deg(np.arccos(cosine.clip(-1, 1)))


def hinges_in_patch(data, region):
    data.calc_loop_triangles()
    triangles = np.asarray([tuple(tri.vertices) for tri in data.loop_triangles])
    adjacent = {}
    for i, (a, b, c) in enumerate(triangles):
        for u, v in ((a, b), (b, c), (c, a)):
            if min(region[u], region[v]) > .4:
                adjacent.setdefault(tuple(sorted((u, v))), []).append(i)
    paired = [(edge, pair) for edge, pair in adjacent.items() if len(pair) == 2]
    tracked, hinges = map(np.asarray, zip(*paired))
    return triangles, tracked, hinges


def measures(mesh, arm, samples, points, fixed, triangles, edges, hinges):
    set_coordinates(mesh.data, points)
    bind_length = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    if np.any(bind_length < .01):
        raise RuntimeError("Collapsed edge in the shoulder surface")
    rest_angles = fold_angles(points, triangles, hinges)
    results, protected = [], []
    for name, frame, reference in samples:
        pose(arm, frame, reference)
        xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
        angles = fold_angles(xyz, triangles, hinges)
        scale = np.linalg.norm(xyz[edges[:, 0]] - xyz[edges[:, 1]], axis=1) / bind_length
        low, high = np.percentile(scale, (1, 99))
        results.append({"clip": name, "frame": frame["frame"], "compression_p01": float(low),
                        "stretch_p99": float(high), "folds_over_100deg": int((angles > 100).sum()),
                        "fold_angle_p99": float(np.percentile(angles, 99))})
        protected.append(xyz[fixed])
    return {
        "rest_folds_over_100deg": int((rest_angles > 100).sum()),
        "rest_fold_angle_p99": float(np.percentile(rest_angles, 99)),
        "peak_motion_folds_over_100deg": max(row["folds_over_100deg"] for row in results),
        "mean_motion_folds_over_100deg": float(np.mean([row["folds_over_100deg"] for row in results])),
        "peak_stretch_p99": max(row["stretch_p99"] for row in results),
        "minimum_compression_p01": min(row["compression_p01"] for row in results),
    }, results, np.array(protected)


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    base = coordinates(mesh.data)
    x, _, z = base.T
    lower = influence(mesh, ("lowerarm", "hand_", "head"))
    region = (smooth(10, 18, np.abs(x)) * (1 - smooth(32, 42, np.abs(x)))
              * smooth(118, 132, z) * (1 - smooth(151, 159, z))
              * (1 - smooth(.05, .48, lower)))
    fixed = region == 0
    edges = np.asarray([tuple(e.vertices) for e in mesh.data.edges])
    triangles, tracked, hinges = hinges_in_patch(mesh.data, region)
    lengths = np.linalg.norm(base[tracked[:, 0]] - base[tracked[:, 1]], axis=1)
    tracked, hinges = tracked[lengths > .08], hinges[lengths > .08]
    samples = list(frames(ROOT / "local/animation-audit", MOTION)) + list(frames(ROOT / "local/idle-audit", IDLE))
    if {sample[0] for sample in samples} != MOTION | IDLE or len(tracked) < 1000:
        raise RuntimeError("Shoulder mesh or original animation samples missing")
    weights = list(weight_candidates(mesh, base, edges, region))
    arms = influence(mesh, ("upperarm", "lowerarm", "hand_"))
    hands = tuple(influence(mesh, (f"hand_{side}",)) > .92 for side in ("l", "r"))
    forearms = tuple((z < 122) & (x * sign > 0) & (influence(mesh, ("lowerarm_",)) > .94)
                    for sign in (1, -1))
    idle = [sample for sample in samples if sample[0] in IDLE]
    torso = (arms < .18) & (z > 56)
    base_clearance = clearance(mesh, arm, idle, base, torso, hands, forearms)
    reference_gap = palm_margin(base_clearance)
    initial, before, anchors = measures(mesh, arm, samples, base, fixed, triangles, tracked, hinges)
    print("v11:", initial, "idle:", reference_gap, worst(base_clearance, "palm"),
          worst(base_clearance, "forearm"), flush=True)
    best = None
    for shape_passes, points in smooth_shape(base, edges, region):
        if not np.array_equal(base[fixed], points[fixed]):
            raise RuntimeError("The shoulder edit moved the face, hands, or lower body")
        for candidate in weights:
            set_weights(mesh, candidate)
            stats, records, protected = measures(mesh, arm, samples, points, fixed, triangles, tracked, hinges)
            if not np.array_equal(anchors, protected):
                raise RuntimeError("The shoulder blend moved a protected region in animation")
            print(shape_passes, candidate[0], stats, flush=True)
            score = (stats["rest_folds_over_100deg"] * 1.5
                     + stats["mean_motion_folds_over_100deg"] * 2
                     + stats["peak_motion_folds_over_100deg"] * .15
                     + stats["peak_stretch_p99"] * 4
                     + (1 - stats["minimum_compression_p01"]) * 4)
            if best is None or score < best[0]:
                best = score, shape_passes, points, candidate, stats, records
    _, shape_passes, points, candidate, final, after = best
    if final["rest_folds_over_100deg"] >= initial["rest_folds_over_100deg"]:
        raise RuntimeError("The candidate did not remove the shoulder folds")
    set_weights(mesh, candidate)
    contact = clearance(mesh, arm, idle, points, torso, hands, forearms)
    print("idle after:", palm_margin(contact), worst(contact, "palm"), worst(contact, "forearm"), flush=True)
    if palm_margin(contact) < reference_gap - .01 or any(
        worst(contact, part) > worst(base_clearance, part) + .001 for part in ("palm", "forearm")
    ):
        raise RuntimeError("The shoulder edit did not preserve idle hand clearance")
    assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices)
    pose(arm, None)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-SmoothShoulders.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-smooth-shoulders.fbx"), [arm, mesh])
    report = {
        "source": "Nailoong-CompactLegs.blend",
        "shape_smoothing_passes": shape_passes,
        "weights": candidate[0],
        "tracked_edges": len(tracked),
        "rest_displacement_max_cm": float(np.linalg.norm(points - base, axis=1).max()),
        "baseline_idle_hand_clearance_cm": reference_gap,
        "minimum_idle_hand_clearance_cm": palm_margin(contact),
        "v11": initial,
        "v12": final,
        "before": before,
        "after": after,
    }
    (OUT / "smooth-shoulders-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({key: value for key, value in report.items() if key not in ("before", "after")})


if __name__ == "__main__":
    main()

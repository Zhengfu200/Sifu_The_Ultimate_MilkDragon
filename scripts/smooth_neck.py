"""Fair the throat and distribute the neck bend across the original Sifu rig."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from fit_idle_arms import clearance, frames, palm_margin, worst
from preview_model import pose
from round_belly import snapshot
from shorten_leg_silhouette import coordinates, influence, set_coordinates, set_weights, smooth


UPPER_BODY = ("spine_01", "spine_02", "spine_03", "neck_01", "neck_02", "head")
MOTION = {
    "MC_man_barehands_V3_north",
    "MC_man_barehands_knockDown_dodge_east",
    "MainChar_Attack_Man_Barehands_Pressure_Jab_FR",
    "MC_man_Staff_Guard_FR",
    "MainChar_Attack_Man_Barehands_Pressure_ElbowMonoStrike_FL",
}
IDLE = {"MC_man_barehands_V0_front", "MC_man_barehands_V0_front_pose"}


def fill_throat(points, edges, arm_share):
    x, y, z = points.T
    freedom = 1 - smooth(.025, .36, arm_share)
    throat = smooth(136, 150, z) * (1 - smooth(150, 160, z))
    front = 1 - smooth(-13, -1, y)
    center = 1 - smooth(10, 21, np.abs(x))
    result = points.copy()
    # Fill the pinched band below the jaw without pulling the mouth forward.
    result[:, 1] -= 4.2 * throat * front * center * freedom

    # Remove small surface ridges left by the earlier piecewise rest fit.
    # The inverse pass limits shrinkage along the round shoulder silhouette.
    region = smooth(133, 143, z) * (1 - smooth(154, 162, z)) * freedom
    a, b = edges[(region[edges] > 0).any(axis=1)].T
    start, end = np.r_[a, b], np.r_[b, a]
    degree = np.bincount(start, minlength=len(points)).clip(min=1)[:, None]
    for _ in range(10):
        for step in (.48, -.44):
            total = np.zeros_like(points)
            np.add.at(total, start, result[end])
            result += step * region[:, None] * (total / degree - result)
    return result


def redistribute(points, original, groups, arm_share, bands):
    z = points[:, 2]
    region = smooth(126, 138, z) * (1 - smooth(157, 163, z)) * (1 - smooth(.025, .32, arm_share))
    ids = np.flatnonzero(region > 1e-6)
    boundaries = [np.ones(len(ids)), *(smooth(lo, hi, z[ids]) for lo, hi in bands), np.zeros(len(ids))]
    profile = np.stack([low - high for low, high in zip(boundaries, boundaries[1:])], axis=1)
    rows = np.zeros((len(ids), len(groups)), dtype=np.float32)
    columns = {int(group): col for col, group in enumerate(groups)}
    for row, vertex, mix, weights in zip(rows, ids, region[ids], profile):
        previous = original[vertex]
        share = sum(previous.get(int(group), 0) for group in groups[:len(UPPER_BODY)])
        for group, weight in previous.items():
            row[columns[group]] = weight
        row[:len(UPPER_BODY)] = row[:len(UPPER_BODY)] * (1 - mix) + weights * share * mix
    # Maintain the influence limit used by the existing model.
    top = np.argsort(rows, axis=1)[:, -4:]
    limited = np.zeros_like(rows)
    np.put_along_axis(limited, top, np.take_along_axis(rows, top, axis=1), axis=1)
    limited[limited < 1e-5] = 0
    limited /= limited.sum(axis=1, keepdims=True)
    return bands, ids, groups, limited


def measure(mesh, arm, samples, points, edges, chest, fixed):
    set_coordinates(mesh.data, points)
    length = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    records, anchors = [], []
    for name, frame, reference in samples:
        pose(arm, frame, reference)
        xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
        scale = np.linalg.norm(xyz[edges[:, 0]] - xyz[edges[:, 1]], axis=1) / length
        lo, hi = np.percentile(scale, (1, 99))
        records.append({"clip": name, "frame": frame["frame"], "compression_p01": float(lo),
                        "stretch_p99": float(hi), "chest_compression_p05": float(np.percentile(scale[chest], 5))})
        anchors.append(xyz[fixed])
    return records, np.array(anchors)


def deviation(records):
    return max(max(r["stretch_p99"] - 1, 1 - r["compression_p01"]) for r in records)


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    base = coordinates(mesh.data)
    z = base[:, 2]
    arms = influence(mesh, ("clavicle_", "upperarm", "lowerarm", "hand_"))
    joints = {b.name: b.matrix_local.copy() for b in arm.data.bones}
    original = snapshot(mesh)
    edges = np.array([tuple(edge.vertices) for edge in mesh.data.edges])
    tracked = edges[((z > 129) & (z < 163) & (arms < .22))[edges].all(axis=1)]
    tracked = tracked[np.linalg.norm(base[tracked[:, 0]] - base[tracked[:, 1]], axis=1) > .12]
    chest = ((z[tracked] < 143) & (base[:, 1][tracked] < 0)).all(axis=1)
    if len(tracked) < 1000:
        raise RuntimeError("Unable to locate the original neck surface")
    samples = (list(frames(ROOT / "local/animation-audit", MOTION))
               + list(frames(ROOT / "local/idle-audit", IDLE)))
    if {name for name, _, _ in samples} != MOTION | IDLE:
        raise RuntimeError("Missing original neck motion samples")

    fixed = (z <= 126) | (z >= 163) | (arms >= .36)
    before, stationary = measure(mesh, arm, samples, base, tracked, chest, fixed)
    revised = fill_throat(base, edges, arms)
    if not np.array_equal(base[fixed], revised[fixed]):
        raise RuntimeError("The neck sculpt changed a protected region")
    group_ids = [mesh.vertex_groups[name].index for name in UPPER_BODY]
    groups = np.array(group_ids + [g.index for g in mesh.vertex_groups if g.index not in group_ids])
    best = None
    baseline_chest = min(r["chest_compression_p05"] for r in before)
    for bands in (
        ((122, 141), (129, 147), (135, 152), (139, 157), (145, 162)),
        ((123, 137), (129, 144), (134, 150), (138, 155), (144, 162)),
        ((121, 139), (127, 145), (134, 151), (139, 154), (145, 160)),
        ((123, 137), (129, 145), (132, 151), (137, 158), (145, 162)),
        ((124, 135), (128, 143), (134, 151), (139, 156), (145, 161)),
    ):
        candidate = redistribute(base, original, groups, arms, bands)
        set_weights(mesh, candidate)
        records, anchors = measure(mesh, arm, samples, revised, tracked, chest, fixed)
        score = deviation(records)
        chest_compression = min(r["chest_compression_p05"] for r in records)
        if not np.array_equal(anchors, stationary):
            raise RuntimeError("The new neck weights moved the face, hands or lower body")
        print(f"{bands}: peak neck strain {score:.2%}; chest compression {chest_compression:.2%}", flush=True)
        if chest_compression < baseline_chest or score >= deviation(before):
            continue
        merit = score + 1 - chest_compression
        if best is None or merit < best[0]:
            best = merit, score, candidate, records
    if best is None:
        raise RuntimeError("No candidate improved the neck without increased chest compression")
    _, score, candidate, after = best
    set_weights(mesh, candidate)

    idle = [sample for sample in samples if sample[0] in IDLE]
    palm = tuple(influence(mesh, (f"hand_{side}",)) > .92 for side in ("l", "r"))
    forearm = tuple((z < 122) & (base[:, 0] * sign > 0) &
                    (influence(mesh, ("lowerarm_",)) > .94) for sign in (1, -1))
    contact = clearance(mesh, arm, idle, revised, (arms < .18) & (z > 56), palm, forearm)
    if palm_margin(contact) < .45 or worst(contact, "palm") > 0 or worst(contact, "forearm") > .01:
        raise RuntimeError("The neck edit did not preserve idle clearance")
    assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices)
    assert all(b.matrix_local == joints[b.name] for b in arm.data.bones)
    pose(arm, None)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-SmoothNeck.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-smooth-neck.fbx"), [arm, mesh])
    report = {
        "source": "Nailoong-CleanFlanks.blend",
        "tracked_edges": len(tracked),
        "max_rest_displacement_cm": float(np.linalg.norm(revised - base, axis=1).max()),
        "position_edits": int(np.count_nonzero(np.any(revised != base, axis=1))),
        "weight_region_vertices": len(candidate[1]),
        "weight_bands_cm": candidate[0],
        "worst_neck_edge_deviation_before": deviation(before),
        "worst_neck_edge_deviation_after": score,
        "minimum_chest_edge_ratio_before": baseline_chest,
        "minimum_chest_edge_ratio_after": min(r["chest_compression_p05"] for r in after),
        "minimum_idle_hand_clearance_cm": palm_margin(contact),
        "before": before,
        "after": after,
    }
    (OUT / "smooth-neck-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({key: value for key, value in report.items() if key not in ("before", "after")})


if __name__ == "__main__":
    main()

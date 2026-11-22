"""Restore the round abdomen from v5 and keep its core rigid in animation."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from fit_idle_arms import clearance, frames, palm_margin, worst
from preview_model import pose
from shorten_leg_silhouette import coordinates, influence, set_coordinates, smooth


def sculpt(v5, v7, torso, arms, width, forward):
    x, y, z = v5.T
    # Restore the smooth unpinched flanks, then move the belly slightly ahead of
    # the hanging hands. Use the same cross section all the way around the body.
    region = (1 - smooth(.025, .72, arms)) * smooth(.60, .98, torso)
    bulk = smooth(63, 90, z) * (1 - smooth(109, 154, z))
    front = 1 - smooth(-27, -13, y)
    out = v7 + (v5 - v7) * region[:, None]
    # Round out the front below the ribs while keeping the side passage for
    # the forearms. The broad face is continuous with the lateral shell.
    out[:, 0] += x * (.17 * front - width) * bulk * region
    out[:, 1] -= forward * bulk * region
    return out


def core_mask(points, torso, arms):
    _, y, z = points.T
    vertical = smooth(65, 95, z) * (1 - smooth(126, 152, z))
    ventral = 1 - smooth(-17, 13, y)
    return vertical * ventral * smooth(.64, .99, torso) * (1 - smooth(0, .12, arms))


def snapshot(mesh):
    return [dict((g.group, g.weight) for g in v.groups) for v in mesh.data.vertices]


def bind_core(mesh, underlying, mix, bone):
    group = mesh.vertex_groups[bone].index
    for i in np.flatnonzero(mix > 1e-5):
        i = int(i)
        value = float(mix[i])
        weights = {k: w * (1 - value) for k, w in underlying[i].items()}
        weights[group] = weights.get(group, 0) + value
        pairs = [(g, w) for g, w in sorted(weights.items(), key=lambda p: -p[1])[:4] if w > 1e-5]
        total = sum(w for _, w in pairs)
        for assignment in list(mesh.data.vertices[i].groups):
            mesh.vertex_groups[assignment.group].remove([i])
        for g, weight in pairs:
            mesh.vertex_groups[g].add([i], weight / total, "REPLACE")
    mesh.data.update()


def score_motion(mesh, arm, clips, points, edges, fixed):
    set_coordinates(mesh.data, points)
    rest = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    if np.any(rest < .015):
        raise RuntimeError("A tracked belly edge was flattened in the bind pose")
    output = []
    protected = []
    for name, frame, reference in clips:
        pose(arm, frame, reference)
        xyz = coordinates(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
        stretch = np.linalg.norm(xyz[edges[:, 0]] - xyz[edges[:, 1]], axis=1) / rest
        low, high = np.percentile(stretch, (1, 99))
        output.append({"clip": name, "frame": frame["frame"], "compression_p01": float(low),
                       "stretch_p99": float(high)})
        protected.append(xyz[fixed])
    return output, np.array(protected)


def strain(records):
    return max(max(r["stretch_p99"] - 1, 1 - r["compression_p01"]) for r in records)


def main():
    # v5 and v7 share topology; the v7 is the exact model currently used by the grip sockets.
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "Nailoong-ShortLegs.blend"), load_ui=False)
    short = coordinates(bpy.data.objects["SK_Nailoong"].data)
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "Nailoong-Grip.blend"), load_ui=False)
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    base = coordinates(mesh.data)
    arms = influence(mesh, ("upperarm", "lowerarm", "hand_"))
    torso = influence(mesh, ("spine_", "pelvis"))
    fixed = (arms > .995) | (base[:, 2] < 63) | (base[:, 2] > 155)
    if not np.array_equal(base[fixed & (base[:, 2] < 63)], short[fixed & (base[:, 2] < 63)]):
        raise RuntimeError("The v5 and v7 mesh vertex orders do not match")
    core = core_mask(short, torso, arms)
    edges = np.array([tuple(e.vertices) for e in mesh.data.edges])
    edges = edges[(core[edges] > .78).all(axis=1)]
    edges = edges[np.linalg.norm(base[edges[:, 0]] - base[edges[:, 1]], axis=1) > .075]
    if len(edges) < 80:
        raise RuntimeError("Could not locate the central belly surface")
    clips = list(frames(ROOT / "local/animation-audit", {
        "MC_man_barehands_V3_north", "MC_man_barehands_knockDown_dodge_east",
        "MainChar_Attack_Man_Barehands_Pressure_Jab_FR", "MC_man_Staff_Guard_FR",
        "MC_man_attack_bats_Light_PushKick_FR",
    }))
    idle = list(frames(ROOT / "local/idle-audit", {
        "MC_man_barehands_V0_front", "MC_man_barehands_V0_front_pose",
    }))
    before, fixed_reference = score_motion(mesh, arm, clips, base, edges, fixed)
    underlying = snapshot(mesh)
    bind_core(mesh, underlying, core, "spine_01")
    zones = ((arms < .18) & (base[:, 2] > 56),
             tuple(influence(mesh, (f"hand_{side}",)) > .92 for side in ("l", "r")),
             tuple((base[:, 2] < 122) & (base[:, 0] * sign > 0) &
                   (influence(mesh, ("lowerarm_",)) > .94) for sign in (1, -1)))
    best = None
    for width, forward in ((.14, 6), (.18, 7), (.22, 8), (.25, 9), (.28, 9), (.30, 10)):
        revised = sculpt(short, base, torso, arms, width, forward)
        tested = clearance(mesh, arm, idle, revised, *zones)
        margin = palm_margin(tested)
        frontarms = worst(tested, "forearm")
        palm = worst(tested, "palm")
        print(f"Width {width:.0%}, forward {forward}: palm gap {margin:.2f}, "
              f"palm penetration {palm:.2%}, forearm penetration {frontarms:.2%}", flush=True)
        key = (max(0, .45 - margin) / 4 + frontarms + palm * 2, width + forward * .012)
        if best is None or key < best[0]:
            best = key, revised, tested, width, forward
    _, revised, tested, width, forward = best
    if palm_margin(tested) < .45 or worst(tested, "palm") > 0 or worst(tested, "forearm") > .01:
        raise RuntimeError("The round belly needs more idle arm clearance")
    after, fixed_after = score_motion(mesh, arm, clips, revised, edges, fixed)
    if strain(after) >= strain(before) or not np.array_equal(fixed_reference, fixed_after):
        raise RuntimeError("The belly change did not stabilize the shape or moved a protected region")
    assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices)
    pose(arm, None)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-RoundBelly.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-round-belly.fbx"), [arm, mesh])
    report = {"model": "Nailoong-RoundBelly", "waist_width_reduction": width,
              "belly_forward_cm": forward, "core_bone": "spine_01",
              "core_edge_count": len(edges), "minimum_idle_clearance_cm": palm_margin(tested),
              "idle_samples": tested, "before": before, "after": after,
              "worst_core_edge_deviation_before": strain(before),
              "worst_core_edge_deviation_after": strain(after)}
    (OUT / "round-belly-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({k: v for k, v in report.items() if k not in ("before", "after", "idle_samples")})


if __name__ == "__main__":
    main()

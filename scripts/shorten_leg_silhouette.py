"""Sculpt a compact silhouette on the seam-fixed model's unchanged game rig."""

import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from preview_model import pose


def smooth(a, b, value):
    t = np.clip((value - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def coordinates(mesh):
    points = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", points)
    return points.reshape(-1, 3)


def set_coordinates(mesh, points):
    mesh.vertices.foreach_set("co", np.ascontiguousarray(points, dtype=np.float32).ravel())
    mesh.update()


def influence(mesh, prefixes):
    groups = {g.index for g in mesh.vertex_groups if g.name.startswith(prefixes)}
    return np.array([sum(g.weight for g in v.groups if g.group in groups) for v in mesh.data.vertices])


def sculpt(points, arm_share, leg_share, foot_share, depth):
    x, y, z = points.T
    result = points.copy()
    torso_clearance = 1 - smooth(.04, .75, arm_share)
    ankle_clearance = 1 - smooth(.02, .65, foot_share)

    # Lower the abdomen and the inseam into the upper thigh, with a long falloff
    # down the leg. Keep the already bound feet at their exact v4 positions.
    hips = smooth(18, 96, z) ** 1.25 * (1 - smooth(96, 147, z))
    result[:, 2] -= depth * hips * torso_clearance * ankle_clearance

    # Keep all details of the face while reducing the height of the neck.
    result[:, 2] -= 7 * smooth(141, 165, z) * torso_clearance

    # Round the lower body and flesh out the thighs and calves. Expand the
    # inner side less than the outer side to leave room during cross-steps.
    belly = smooth(68, 101, z) * (1 - smooth(117, 145, z)) * torso_clearance
    result[:, 0] += .16 * x * belly
    result[:, 1] += .035 * y * belly
    leg_bulk = smooth(12, 35, z) * (1 - smooth(82, 116, z)) * leg_share * ankle_clearance
    center = np.interp(z, (10, 54.5, 100.3), (15.5, 12.2, 8.6))
    radial_x = np.abs(x) - center
    calf = 1 - smooth(44, 72, z)
    strength = np.where(radial_x >= 0, .36 + .38 * calf, .13 + .15 * calf)
    result[:, 0] += np.sign(x) * radial_x * strength * leg_bulk
    result[:, 1] += (y - 2.5) * .10 * leg_bulk
    return result


def relaxed_weights(mesh, points, leg, foot):
    # Restrict the smoothing pass to the hip and knee transitions. Both soles
    # and their nearby anchors stay exactly as they were in the seam-fixed mesh.
    names = tuple(g.name for g in mesh.vertex_groups)
    groups = np.array([i for i, name in enumerate(names)
                       if name.startswith(("thigh_", "calf_", "foot_", "ball_", "pelvis", "spine_"))])
    lookup = {g: i for i, g in enumerate(groups)}
    z = points[:, 2]
    mix = smooth(.03, .5, leg) * smooth(13, 33, z) * (1 - smooth(.02, .25, foot))
    ids = np.flatnonzero(mix > 0)
    edges = np.array([tuple(e.vertices) for e in mesh.data.edges])
    edges = edges[(mix[edges] > 0).any(axis=1)]
    a = np.r_[edges[:, 0], edges[:, 1]]
    b = np.r_[edges[:, 1], edges[:, 0]]
    values = np.zeros((len(points), len(groups)), dtype=np.float32)
    for vertex in mesh.data.vertices:
        for g in vertex.groups:
            if g.group in lookup:
                values[vertex.index, lookup[g.group]] = g.weight
            elif mix[vertex.index] > 0:
                raise RuntimeError("Leg region unexpectedly contains an unrelated vertex group")
    counts = np.bincount(a, minlength=len(points)).clip(min=1)[:, None]
    original = values[ids].copy()
    yield 0, ids, groups, original
    for step in range(1, 55):
        average = np.zeros_like(values)
        np.add.at(average, a, values[b])
        values[ids] += .5 * mix[ids, None] * (average[ids] / counts[ids] - values[ids])
        if step in (8, 20, 36, 54):
            data = values[ids]
            top = np.argsort(data, axis=1)[:, -4:]
            limited = np.zeros_like(data)
            np.put_along_axis(limited, top, np.take_along_axis(data, top, axis=1), axis=1)
            limited[limited < 1e-5] = 0
            limited /= limited.sum(axis=1, keepdims=True)
            yield step, ids, groups, limited


def set_weights(mesh, candidate):
    _, ids, groups, rows = candidate
    for vertex_id, row in zip(ids, rows):
        vertex_id = int(vertex_id)
        for assignment in list(mesh.data.vertices[vertex_id].groups):
            mesh.vertex_groups[assignment.group].remove([vertex_id])
        for column in np.flatnonzero(row):
            mesh.vertex_groups[int(groups[column])].add([vertex_id], float(row[column]), "REPLACE")
    mesh.data.update()


def assess(mesh, arm, points, reference, leg, foot, baseline=None):
    # Compare the same edges and same sole vertices on each bound mesh.
    edges = np.array([tuple(e.vertices) for e in mesh.data.edges])
    edges = edges[(leg[edges] > .25).any(axis=1)]
    initial_length = np.linalg.norm(reference[edges[:, 0]] - reference[edges[:, 1]], axis=1)
    edges = edges[initial_length > .08]
    bind = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    sole = (foot > .9) & (reference[:, 2] < 2)
    region = ("north", "PushKick", "dodge_east")
    clips = [p for p in sorted((ROOT / "local/animation-audit").glob("*.anim.json"))
             if any(name in p.name for name in region)]
    if len(clips) != 3 or not sole.any():
        raise RuntimeError("Expected the run, kick and dodge samples and sole vertices")
    report, foot_samples = [], []
    set_coordinates(mesh.data, points)

    def evaluate():
        evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return coordinates(evaluated.data)

    for path in clips:
        clip = json.loads(path.read_text(encoding="utf-8"))
        refs = {b["name"]: b for b in clip["reference"]}
        metrics, clip_feet = [], []
        for sample, frame in enumerate(clip["frames"]):
            pose(arm, frame, refs)
            animated = evaluate()
            if not np.isfinite(animated).all():
                raise RuntimeError("Invalid skinned coordinates")
            current = np.linalg.norm(animated[edges[:, 0]] - animated[edges[:, 1]], axis=1)
            low, high = np.percentile(current / bind, (1, 99))
            shift = 0 if baseline is None else np.max(np.abs(animated[sole] - baseline[len(report)][sample]))
            metrics.append((low, high, shift))
            clip_feet.append(animated[sole])
        samples = np.asarray(metrics)
        report.append({
            "clip": clip["name"],
            "frames": len(samples),
            "leg_compression_p01_min": float(samples[:, 0].min()),
            "leg_stretch_p99_peak": float(samples[:, 1].max()),
            "maximum_sole_shift_cm": float(samples[:, 2].max()),
        })
        foot_samples.append(np.array(clip_feet))
    pose(arm, None)
    return report, foot_samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=float, default=24)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if not 0 < args.depth <= 32:
        raise ValueError("Choose a hip adjustment between 0 and 32 cm")
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = bpy.data.objects["Armature"]
    original = coordinates(mesh.data)
    arm_share = influence(mesh, ("upperarm", "lowerarm", "hand_"))
    leg_share = influence(mesh, ("thigh_", "calf_"))
    foot_share = influence(mesh, ("foot_", "ball_"))
    revised = sculpt(original, arm_share, leg_share, foot_share, args.depth)
    assert np.array_equal(revised[original[:, 2] <= 12], original[original[:, 2] <= 12])
    assert np.array_equal(revised[arm_share > .995], original[arm_share > .995])
    baseline, soles = assess(mesh, arm, original, original, leg_share, foot_share)
    candidates = tuple(relaxed_weights(mesh, original, leg_share, foot_share))
    best = None
    for candidate in candidates:
        set_weights(mesh, candidate)
        samples, _ = assess(mesh, arm, revised, original, leg_share, foot_share, soles)
        score = max(record["leg_stretch_p99_peak"] for record in samples) - min(
            record["leg_compression_p01_min"] for record in samples)
        print("Weight smoothing", candidate[0], "score", round(score, 3), flush=True)
        if best is None or score < best[0]:
            best = score, candidate, samples
    _, candidate, samples = best
    set_weights(mesh, candidate)
    assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices)
    if any(record["maximum_sole_shift_cm"] > .001 for record in samples):
        raise RuntimeError("The edited model moves the sole during animation")

    middle = np.abs(original[:, 0]) < .15
    report = {"depth_cm": args.depth, "weight_smoothing_passes": candidate[0],
              "samples": samples, "baseline": baseline}
    for label, points in (("v4", original), ("revised", revised)):
        floor = float(points[:, 2].min())
        report[label] = {"height_cm": float(points[:, 2].max()) - floor,
                         "inseam_cm": float(points[middle, 2].min()) - floor}
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-ShortLegs.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-short-legs.fbx"), [arm, mesh])
    (OUT / "short-legs-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

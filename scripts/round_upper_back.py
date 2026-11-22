"""Remove the nape hump while preserving the v13 front and limbs."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blend_shoulders import adjacency, hinges_in_patch
from build_model import OUT, ROOT, sifu
from fit_idle_arms import frames
from preview_model import pose
from relax_guard_neck import measure, summary
from shorten_leg_silhouette import coordinates, influence, smooth
from smooth_neck import IDLE, MOTION


def back_envelope(tree, heights):
    samples = []
    for height in heights:
        hits = [tree.ray_cast(Vector((x, 55, height)), Vector((0, -1, 0)))[0]
                for x in (-2, 0, 2)]
        if any(hit is None for hit in hits):
            raise RuntimeError("Unable to measure the upper back")
        samples.append(np.median([hit.y for hit in hits]))
    return np.array(samples)


def back_arc(z):
    # Cubic segments with shared tangents keep the curve smooth into the
    # existing head and lower back. Keep a gentle roundness at the shoulders.
    heights = np.array([105, 116, 130, 141, 149, 159, 166])
    depth = np.array([18.7, 18.5, 18.8, 18.7, 16.9, 13.8, 11.4])
    tangent = np.array([-.12, 0., .016, -.10, -.30, -.34, -.34])
    i = (np.searchsorted(heights, z) - 1).clip(0, len(heights) - 2)
    width = heights[i + 1] - heights[i]
    t = ((z - heights[i]) / width).clip(0, 1)
    s = t * t * (3 - 2 * t)
    return ((1 - s) * depth[i] + s * depth[i + 1]
            + width * t * (1 - t) * ((1 - t) * tangent[i] - t * tangent[i + 1]))


def sculpt(base, edges, region, envelope):
    z = base[:, 2]
    samples, measured = envelope
    delta = back_arc(z) - np.interp(z, samples, measured)
    points = base.copy()
    points[:, 1] += region * delta
    # Blend the base of the head into the new arc on the actual mesh.
    fair = region * smooth(114, 129, z) * (1 - smooth(151, 164, z))
    start, end, degree = adjacency(edges, fair)
    for _ in range(16):
        average = np.zeros_like(points)
        np.add.at(average, start, points[end])
        points += .36 * fair[:, None] * (average / degree - points)
    return points


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = mesh.parent
    base = coordinates(mesh.data)
    x, y, z = base.T
    limbs = influence(mesh, ("clavicle_", "upperarm", "lowerarm", "hand_"))
    pad = (1 - smooth(9, 23, np.abs(x))) * (1 - smooth(.05, .27, limbs)) * smooth(6, 13, y)
    region = pad * smooth(105, 118, z) * (1 - smooth(156, 165, z))
    fixed = region == 0
    edges = np.array([tuple(edge.vertices) for edge in mesh.data.edges])
    triangles, tracked, hinges = hinges_in_patch(mesh.data, region * smooth(114, 125, z))
    length = np.linalg.norm(base[tracked[:, 0]] - base[tracked[:, 1]], axis=1)
    keep = (length > .09) & (z[tracked].max(axis=1) < 159)
    tracked, hinges = tracked[keep], hinges[keep]
    clips = list(frames(ROOT / "local/animation-audit", MOTION)) + list(frames(ROOT / "local/idle-audit", IDLE))
    if len(tracked) < 600 or {sample[0] for sample in clips} != MOTION | IDLE:
        raise RuntimeError("Missing upper-back mesh or animation samples")
    samples = np.arange(105., 166.1, .5)
    envelope = back_envelope(BVHTree.FromPolygons(base.tolist(), triangles.tolist(), all_triangles=True), samples)
    before, anchors = measure(mesh, arm, clips, base, triangles, tracked, hinges, fixed)
    baseline = summary(before)
    points = sculpt(base, edges, region, (samples, envelope))
    after, protected = measure(mesh, arm, clips, points, triangles, tracked, hinges, fixed)
    if not np.array_equal(anchors, protected):
        raise RuntimeError("The back edit moved a protected region in animation")
    result = summary(after)
    if (result["stretch_p99_peak"] > 1.1 * baseline["stretch_p99_peak"]
            or result["compression_p05_minimum"] < .90 * baseline["compression_p05_minimum"]):
        raise RuntimeError("Back adjustment exceeded the motion limits")
    revised = back_envelope(BVHTree.FromPolygons(points.tolist(), triangles.tolist(), all_triangles=True), samples)
    peak_zone = (samples >= 136) & (samples <= 150)
    reduction = float(envelope[peak_zone].max() - revised[peak_zone].max())
    if reduction < 2:
        raise RuntimeError("The upper-back hump remains in the silhouette")
    if not all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
               for v in mesh.data.vertices):
        raise RuntimeError("Invalid skin weights")
    pose(arm, None)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-RoundBack.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-round-back.fbx"), [arm, mesh])
    report = {
        "source": "Nailoong-GuardNeck.blend", "frames": len(after), "weights": "v13",
        "peak_back_reduction_cm": reduction,
        "profile_height_cm": samples.tolist(), "profile_before_cm": envelope.tolist(),
        "profile_after_cm": revised.tolist(), "motion_before": baseline, "motion_after": result,
        "before": before, "after": after,
    }
    (OUT / "round-back-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Peak back reduction:", round(reduction, 2), "cm. Motion:", baseline, "->", result)


if __name__ == "__main__":
    main()

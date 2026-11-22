"""Locally refine the existing v2 arm weights and export an editable copy.

Compare the same mesh edges in the same game poses while keeping the reference
mesh and skeleton fixed. Keep the original weights when a local edit scores worse.
"""

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_model import OUT, sifu
from preview_model import pose


def smooth(lo, hi, values):
    t = np.clip((values - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def limited(weights):
    """Apply the same four influences and normalized totals used in the game build."""
    result = weights.copy()
    keep = np.argsort(result, axis=1)[:, -4:]
    result.fill(0)
    np.put_along_axis(result, keep, np.take_along_axis(weights, keep, axis=1), axis=1)
    result[result < 1e-5] = 0
    result /= result.sum(axis=1, keepdims=True)
    return result


class ArmReview:
    def __init__(self, mesh, arm, side, frames):
        self.side = side
        self.mesh = mesh
        self.names = [g.name for g in mesh.vertex_groups]
        self.group = {name: i for i, name in enumerate(self.names)}
        self.limb_groups = [i for i, name in enumerate(self.names) if
                            name.endswith("_" + side) and name.startswith(("upperarm", "lowerarm", "hand_"))]
        full_weights = np.zeros((len(mesh.data.vertices), len(self.names)), dtype=np.float32)
        for vertex in mesh.data.vertices:
            for g in vertex.groups:
                full_weights[vertex.index, g.group] = g.weight
        # Include both the arm and the vertices at its blend into the torso.
        affected = full_weights[:, self.limb_groups].sum(axis=1) > 0
        edges = np.array([tuple(edge.vertices) for edge in mesh.data.edges
                          if any(affected[i] for i in edge.vertices)])
        self.vertex_ids = np.unique(edges)
        self.edges = np.searchsorted(self.vertex_ids, edges)
        self.original = full_weights[self.vertex_ids]
        self.weights = self.original.copy()
        self.points = np.array([tuple(mesh.data.vertices[int(i)].co) for i in self.vertex_ids], dtype=np.float32)
        p = np.c_[self.points, np.ones(len(self.points), dtype=np.float32)]
        # Reduce the transform bank to bones with actual influences on this region.
        self.active = np.flatnonzero(self.weights.max(axis=0))
        self.transforms = {}
        for group in self.active:
            name = self.names[group]
            self.transforms[group] = np.einsum("fij,vj->fvi", frames[name], p, optimize=True)
        self.base_lengths = np.linalg.norm(self.points[self.edges[:, 0]] - self.points[self.edges[:, 1]], axis=-1)
        self.arm_share = self.original[:, self.limb_groups].sum(axis=1)
        shoulder, elbow, hand = [np.array(arm.data.bones[f"{name}_{side}"].head_local) for
                                 name in ("upperarm", "lowerarm", "hand")]
        self.elbow = (self.points - elbow) @ self.axis(shoulder, elbow)
        self.wrist = (self.points - hand) @ self.axis(elbow, hand)
        self.results = {}

    @staticmethod
    def axis(a, b):
        return (b - a) / np.linalg.norm(b - a)

    def change(self, chosen, candidates, name):
        edges = self.edges
        region = chosen[edges].any(axis=1) & (self.base_lengths > .035)
        edges = edges[region]
        verts = np.unique(edges)
        local_edges = np.searchsorted(verts, edges)
        lengths = self.base_lengths[region]
        bank = {group: self.transforms[group][:, verts] for group in self.active}

        def score(weights):
            points = sum(t * weights[None, verts, group, None] for group, t in bank.items())
            ratios = np.linalg.norm(points[:, local_edges[:, 0]] - points[:, local_edges[:, 1]], axis=-1) / lengths
            p05, p95, p99 = np.percentile(ratios, [5, 95, 99], axis=1)
            # Score both pinching and stretching across the sample, including the worst frames.
            distortion = (p95 - 1) + (1 - p05)
            return {
                "score": float(distortion.mean() + .35 * p99.max()),
                "stretch_p99_peak": float(p99.max()),
                "compression_p05_minimum": float(p05.min()),
            }

        before = score(self.weights)
        best, best_name, best_weights = before, "v2", self.weights
        for label, weights in candidates:
            weights = limited(weights)
            result = score(weights)
            # Avoid trading most of the gain for a visible new crease.
            if (result["compression_p05_minimum"] >= .86 * before["compression_p05_minimum"]
                    and result["score"] < best["score"]):
                best, best_name, best_weights = result, label, weights
        count = int(np.count_nonzero(np.max(np.abs(best_weights - self.weights), axis=1) > 1e-4))
        self.results[name] = {"choice": best_name, "edited_vertices": count, "before": before, "after": best}
        self.weights = best_weights

    def smooth_candidates(self, falloff, iterations):
        """Average adjacent vertex weights inside the edit, holding its border fixed."""
        rows = np.concatenate((self.edges[:, 0], self.edges[:, 1]))
        columns = np.concatenate((self.edges[:, 1], self.edges[:, 0]))
        neighbors = np.maximum(1, np.bincount(rows, minlength=len(self.vertex_ids)))[:, None]
        values = self.weights[:, self.active].copy()
        for i in range(1, max(iterations) + 1):
            averages = np.zeros_like(values)
            np.add.at(averages, rows, values[columns])
            values += (averages / neighbors - values) * falloff[:, None] * .5
            if i in iterations:
                weights = self.weights.copy()
                weights[:, self.active] = values
                yield f"local smooth, {i} passes", weights

    def wrist_pass(self):
        hand = self.group[f"hand_{self.side}"]
        region = (self.arm_share > .995) & (self.wrist > -9) & (self.wrist < 4)
        candidates = []
        for start, end in [(-7, 1), (-6, 2), (-5, 1), (-5, 2), (-4, 1), (-4, 2), (-3, 1)]:
            desired = smooth(start, end, self.wrist)
            has_forearm = region & (self.weights[:, hand] < 1 - 1e-5)
            for mix in (.5, 1.0):
                indices = np.flatnonzero(has_forearm)
                weights = self.weights.copy()
                old = weights[indices, hand]
                new = old + mix * (desired[indices] - old)
                weights[indices] *= ((1 - new) / (1 - old))[:, None]
                weights[indices, hand] = new
                # The palm beyond the adjusted transition stays entirely on hand.
                candidates.append((f"{start}cm to {end}cm, {mix:.0%}", weights))
        self.change(region, candidates, "wrist")

    def elbow_pass(self):
        upper = self.group[f"upperarm_twist_04_{self.side}"]
        lower = self.group[f"lowerarm_{self.side}"]
        region = (self.arm_share > .97) & (self.elbow > -8) & (self.elbow < 7) & (self.wrist < -9)
        amount = smooth(-8, -3, self.elbow) * (1 - smooth(2, 7, self.elbow)) * region
        candidates = []
        for lo, hi in [(-6, 4), (-5, 5), (-4, 3), (-4, 5), (-3, 3)]:
            lower_share = smooth(lo, hi, self.elbow)
            for mix in (.35, .65, 1):
                blend = amount * mix
                weights = self.weights * (1 - blend[:, None])
                weights[:, upper] += blend * (1 - lower_share)
                weights[:, lower] += blend * lower_share
                candidates.append((f"{lo}cm to {hi}cm, {mix:.0%}", weights))
        candidates.extend(self.smooth_candidates(amount, (5, 15, 35, 65)))
        self.change(region, candidates, "elbow")

    def shoulder_pass(self):
        # Taper small arm influences on the torso side of the armpit. Redistribute
        # that portion to the existing torso groups for those same vertices.
        region = (self.arm_share < .99) & (self.arm_share > 0)
        candidates = []
        for cutoff in (.15, .25, .35, .5):
            taper = (1 - smooth(.02, cutoff, self.arm_share)) * region
            for mix in (.35, .70, 1):
                weights = self.weights.copy()
                arm_scale = 1 - taper * mix
                indices = np.flatnonzero(region)
                other = np.setdiff1d(self.active, self.limb_groups)
                weights[np.ix_(indices, self.limb_groups)] *= arm_scale[indices, None]
                torso_scale = (1 - self.arm_share[indices] * arm_scale[indices]) / (1 - self.arm_share[indices])
                weights[np.ix_(indices, other)] *= torso_scale[:, None]
                candidates.append((f"taper below {cutoff:.0%}, {mix:.0%}", weights))
        falloff = smooth(0, .08, self.arm_share) * (1 - smooth(.89, 1, self.arm_share)) * region
        candidates.extend(self.smooth_candidates(falloff, (6, 15, 35, 65)))
        self.change(region, candidates, "shoulder")

    def apply(self):
        changed = np.flatnonzero(np.max(np.abs(self.weights - self.original), axis=1) > 1e-4)
        for row in changed:
            vertex = int(self.vertex_ids[row])
            for old in list(self.mesh.data.vertices[vertex].groups):
                self.mesh.vertex_groups[old.group].remove([vertex])
            for group in np.flatnonzero(self.weights[row]):
                self.mesh.vertex_groups[int(group)].add([vertex], float(self.weights[row, group]), "REPLACE")
        return len(changed)


def collect_poses(arm):
    matrices = {bone.name: [] for bone in arm.pose.bones}
    inverse = {bone.name: bone.bone.matrix_local.inverted() for bone in arm.pose.bones}
    for path in sorted((ROOT / "local/animation-audit").glob("*.anim.json")):
        clip = json.loads(path.read_text(encoding="utf-8"))
        refs = {b["name"]: b for b in clip["reference"]}
        for frame in clip["frames"]:
            pose(arm, frame, refs)
            for bone in arm.pose.bones:
                matrices[bone.name].append(tuple(tuple(row) for row in (bone.matrix @ inverse[bone.name])[:3]))
    pose(arm, None)
    return {name: np.array(values, dtype=np.float32) for name, values in matrices.items()}


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    arm = bpy.data.objects["Armature"]
    assert bpy.context.mode == "OBJECT"
    assert not mesh.modifiers["Sifu skeleton"].use_deform_preserve_volume
    assert mesh.matrix_world == Matrix.Identity(4) and arm.matrix_world == Matrix.Identity(4)
    poses = collect_poses(arm)
    report = {"pose_count": len(poses["root"]), "sides": {}}
    for side in ("l", "r"):
        review = ArmReview(mesh, arm, side, poses)
        review.wrist_pass()
        review.elbow_pass()
        review.shoulder_pass()
        report["sides"][side] = {"edited_vertices": review.apply(), "regions": review.results}
    assert sum(side["edited_vertices"] for side in report["sides"].values())
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-Manual.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-manual.fbx"), [arm, mesh])
    (OUT / "manual-weight-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Render local stills of the bound mesh from Sifu's decoded animation poses."""

import json
import sys
import argparse
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, sifu


def pose(armature, frame, references=None):
    animation = {bone["name"]: bone for bone in frame["bones"]} if frame else {}
    for bone in armature.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
        sample = animation.get(bone.name)
        if not sample or not sample["keyed"]:
            continue
        rest = bone.bone.matrix_local.copy()
        if bone.parent:
            rest = bone.parent.bone.matrix_local.inverted() @ rest
        target = sifu.bl_to_ue(rest)
        source = references[bone.name]
        source_matrix = sifu.ue_local(source["transform"])
        t = Vector(sample["t"])
        x, y, z, w = sample["q"]
        q = Quaternion((w, x, y, z))
        scale = Vector(sample.get("s", (1, 1, 1)))
        mode = source["mode"]
        src_t, dst_t = source_matrix.translation, target.translation
        if mode == "Skeleton":
            t = dst_t.copy()
        elif mode == "AnimationScaled" and src_t.length > 1e-6:
            t *= dst_t.length / src_t.length
        elif mode == "AnimationRelative":
            q = q @ source_matrix.to_quaternion().inverted() @ target.to_quaternion()
            t += dst_t - src_t
            scale = Vector(a * b / c if abs(c) > 1e-8 else 0 for a, b, c in
                           zip(scale, target.to_scale(), source_matrix.to_scale()))
        elif mode == "OrientAndScale":
            if (t - src_t).length < .001:
                t = dst_t.copy()
            elif src_t.length > 1e-6 and dst_t.length > 1e-6:
                t = src_t.rotation_difference(dst_t) @ t * (dst_t.length / src_t.length)
        elif mode not in ("Animation", "AnimationScaled", "OrientAndScale"):
            raise RuntimeError("Unhandled retarget mode: " + mode)
        animated = q.to_matrix().to_4x4() @ Matrix.Diagonal((*scale, 1))
        animated.translation = t
        # Render in place; the root's rotation is still applied.
        if bone.parent is None:
            animated.translation = target.translation
        bone.matrix_basis = rest.inverted() @ sifu.ue_to_bl(animated)
    bpy.context.view_layer.update()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, default=OUT / "previews")
    parser.add_argument("--sample-stride", type=int, default=1)
    parser.add_argument("--upper-body", action="store_true")
    parser.add_argument("--flat", action="store_true", help="Show base color without light or shadows.")
    parser.add_argument("--both-sides", action="store_true", help="Render the opposite three-quarter angle too.")
    parser.add_argument("--profile", action="store_true", help="Render side and rear three-quarter views.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    paths = args.paths
    armature = bpy.data.objects["Armature"]
    for obj in bpy.context.scene.objects:
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE":
                modifier.use_deform_preserve_volume = False
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.light = "FLAT" if args.flat else "STUDIO"
    scene.display.shading.show_shadows = not args.flat
    if args.flat:
        scene.display.shading.show_cavity = False
        scene.display.shading.show_specular_highlight = False
    scene.render.resolution_x = 520
    scene.render.resolution_y = 620
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    camera_data = bpy.data.cameras.new("Pose preview")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 125 if args.upper_body else 230
    camera_data.clip_end = 10000
    camera = bpy.data.objects.new("Pose preview", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    output = args.output
    if not output.is_absolute():
        output = OUT.parents[1] / output
    output.mkdir(exist_ok=True, parents=True)
    views = {"front": (0, -360, 105), "three-quarter": (240, -310, 132)}
    if args.both_sides:
        views["opposite-side"] = (-240, -310, 132)
    if args.profile:
        height = 132 if args.upper_body else 93
        views = {"profile": (-390, 0, height), "rear-quarter": (-340, 185, height)}
    focus = Vector((0, 0, 132 if args.upper_body else 93))
    samples = [("Rest", None, None)]
    for path in paths:
        animation = json.loads(path.read_text(encoding="utf-8-sig"))
        if "reference" not in animation or animation.get("additive") != "AAT_None":
            raise RuntimeError("Re-export this non-additive clip with AnimationAudit: " + str(path))
        references = {b["name"]: b for b in animation["reference"]}
        samples.extend((f"{animation['name']}-{int(frame['frame']):02}", frame, references)
                       for frame in animation["frames"][::args.sample_stride])
    for name, frame, references in samples:
        pose(armature, frame, references)
        target = focus
        if args.upper_body and frame:
            bones = armature.pose.bones
            target = armature.matrix_world @ bones["spine_01"].head.lerp(bones["head"].head, .42)
        for view, location in views.items():
            camera.location = Vector(location) + target - focus
            camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(output / f"{name}-{view}.png")
            bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()

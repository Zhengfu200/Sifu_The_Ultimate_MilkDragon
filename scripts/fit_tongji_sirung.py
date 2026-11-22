"""Fit the original SIRUNG glTF to the blue-and-white Nailoong outfit."""

import argparse
from math import hypot
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, select, sifu
from build_tongji import save_texture
from clean_flank_color import pixels


WORK = ROOT / "build/tongji/sirung"
SOURCE = ROOT / "source/nailoong/skins/tongji/sirung_conical_hat.glb"
SLOT = "M_Nailoong_Tongji_Sirung"
ALBEDO = "T_Nailoong_Tongji_Sirung_BaseColor"


def smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brim-height", type=float, default=165.6, help="Height of the brim center in scene cm")
    parser.add_argument("--tilt", type=float, default=.22, help="Vertical rise per cm toward the back")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    WORK.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(OUT.parent / "tongji/Nailoong-Tongji.blend"), load_ui=False)
    body = bpy.data.objects["SK_Nailoong"]
    arm = bpy.data.objects["Armature"]

    existing = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    imported = set(bpy.data.objects) - existing
    parts = {obj.name: obj for obj in imported if obj.type == "MESH"}
    shell = parts["Cone_Default_0"]
    crown = parts["Mesh_Default_0"]
    assert len(parts) == 2 and shell.data.materials[0] == crown.data.materials[0]
    material = shell.data.materials[0]
    material.name = SLOT
    texture = next(node for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
    material.node_tree.nodes.active = texture
    texture.image.pack()
    albedo = pixels(texture.image).reshape(texture.image.size[1], texture.image.size[0], 4)
    albedo[:, :, 3] = 0
    game = save_texture(ALBEDO, albedo)
    game.filepath_raw = str(WORK / (ALBEDO + ".png"))
    game.save()
    bpy.data.images.remove(game)

    # Keep the source UVs and the two original mesh parts, including the woven peak.
    bpy.context.view_layer.update()
    transforms = {obj: obj.matrix_world.copy() for obj in parts.values()}
    brim = min((transforms[shell] @ vertex.co).z for vertex in shell.data.vertices)
    for obj in (shell, crown):
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        for vertex in obj.data.vertices:
            x, y, z = transforms[obj] @ vertex.co
            x *= .00185
            y *= .00195
            # Lower the front and side rim smoothly while leaving the crown and rear rim supported by the head.
            radius = hypot(x / 32.8, y / 27.3)
            front_rim = smoothstep((radius - .43) / .57) * (1 - smoothstep((y + 1) / 17))
            side_drop = 4.5 * smoothstep(abs(x) / 21)
            height = (z - brim) * .00168 * .93
            z = args.brim_height + height + args.tilt * y - side_drop * front_rim
            vertex.co = (x, y - 8.5, z)
        obj.data.update()
    for obj in imported - set(parts.values()):
        bpy.data.objects.remove(obj, do_unlink=True)

    # The UE body master is one-sided. Give the shell an interior using its own UVs.
    select(shell)
    lining = shell.modifiers.new("Woven shell thickness", "SOLIDIFY")
    lining.thickness = .26
    bpy.ops.object.modifier_apply(modifier=lining.name)
    crown.select_set(True)
    bpy.ops.object.join()
    hat = bpy.context.object
    hat.name = "SIRUNG Conical Hat"
    assert len(hat.material_slots) == 1 and "head" in arm.data.bones
    hat.parent = arm
    hat.vertex_groups.new(name="head").add(list(range(len(hat.data.vertices))), 1, "REPLACE")
    hat.modifiers.new("Sifu skeleton", "ARMATURE").object = arm
    hat["Source"] = "SIRUNG Conical Hat by eeelabvisual, CC BY 4.0"
    hat["Source URL"] = "https://sketchfab.com/3d-models/sirung-conical-hat-83c5b31a35b54052bfd43da6ad37db21"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK / "Nailoong-Tongji-Sirung.blend"))
    sifu.export_fbx(str(WORK / "SK_Nailoong_Tongji.fbx"), [arm, body, hat])


if __name__ == "__main__":
    main()

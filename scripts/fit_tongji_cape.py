"""Fit Karnage's cape to the Tongji outfit and bind it to the Sifu skeleton."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import ROOT, select, sifu
from build_tongji import save_texture
from build_wanderer import ease


WORK = ROOT / "build/tongji/cape"
SOURCE = ROOT / "source/nailoong/skins/tongji/cape.glb"
SLOT = "M_Nailoong_Tongji_Cape"
ALBEDO = "T_Nailoong_Tongji_Cape_BaseColor"
PROXY_SLOT = "M_Nailoong_Tongji_ClothProxy"
MAX_DISTANCE = 62


def import_cape():
    existing = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    imported = set(bpy.data.objects) - existing
    source = next(obj for obj in imported if obj.type == "MESH" and obj.vertex_groups)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(graph)
    data = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
    # Freeze the author's displayed drape before rebinding it to the game rig.
    transform = evaluated.matrix_world.copy()
    for vertex in data.vertices:
        vertex.co = (transform @ vertex.co) / 100
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    weld = bmesh.new()
    weld.from_mesh(data)
    deform = weld.verts.layers.deform.active
    if deform is not None:
        weld.verts.layers.deform.remove(deform)
    bmesh.ops.remove_doubles(weld, verts=list(weld.verts), dist=.00001)
    weld.to_mesh(data)
    weld.free()
    data.update()
    return data


def fit(data, body, long_cape):
    tree = BVHTree.FromPolygons([vertex.co for vertex in body.vertices],
                                [face.vertices[:] for face in body.polygons])
    for vertex in data.vertices:
        source_x, source_y, source_z = vertex.co
        height = (source_z - .305) / (1.800 - .305)
        collar = ease(1.52, 1.77, source_z)
        x = source_x * (82 + 19 * collar)
        z = 62 + 93 * height
        if long_cape:
            z -= 35 * (1 - ease(65, 142, z))
        back = 23 + source_y * 58 + 5 * (1 - height)
        y = (1 - collar) * back + collar * (source_y * 123 - 10)
        # Seat the collar over the shoulder surface, leaving room for the lining.
        if z > 134:
            center = Vector((0, 1, z))
            radial = Vector((x, y - center.y, 0))
            if radial.length > .01:
                direction = radial.normalized()
                contact = tree.ray_cast(center + direction * 52, -direction, 52)[0]
                if contact is not None:
                    radius = (contact - center).length
                    clearance = 3.5 + 3.0 * ease(8, 24, abs(x)) + 1.0 * ease(0, 15, y)
                    if radial.length < radius + clearance:
                        x, y, _ = center + direction * (radius + clearance)
        vertex.co = (x, y, z)
    data.update()


def fit_back_panel(data, torso):
    """Follow the back of the torso and let the hem hang behind the legs."""
    for vertex in data.vertices:
        x, y, z = vertex.co
        # Retain the wraparound collar. Blend the rear shoulder seam into the hanging panel.
        panel = (1 - ease(142, 152, z)) * ease(7, 24, y)
        if panel <= 0:
            continue
        # Follow the back without folding the outer edges around the arms.
        profile_x = x / (1 + (x / 20) ** 4) ** .25
        contact = torso.ray_cast((profile_x, 80, max(87, z)), (0, -1, 0), 80)[0]
        if contact is None:
            contact = torso.ray_cast((0, 80, max(87, z)), (0, -1, 0), 80)[0]
        if contact is None:
            continue
        pleat = max(-1.1, min(1.1, .24 * (y - (37 + .09 * (140 - z)))))
        back_y = contact.y + 2.8 + pleat
        # Leave extra room at the outside edges where the upper arms swing behind the torso.
        arm_clearance = ease(12, 24, abs(x)) * ease(85, 109, z)
        back_y += arm_clearance * max(0, 25 + pleat - back_y)
        hanging_y = 24 + pleat
        target = hanging_y + ease(72, 99, z) * (back_y - hanging_y)
        vertex.co.y += panel * (target - y)
    data.update()


def fabric():
    size = 512
    v, u = np.mgrid[:size, :size] / size
    weave = .004 * np.sin(2 * np.pi * 128 * u) * np.cos(2 * np.pi * 128 * v)
    grain = np.random.default_rng(24).normal(0, .0025, (size, size))
    rgba = np.ones((size, size, 4), dtype=np.float32)
    rgba[:, :, :3] = np.array((45, 58, 73)) / 255 + (weave + grain)[:, :, None]
    preview = save_texture(ALBEDO + "_Preview", rgba)
    preview.pack()
    rgba[:, :, 3] = 0
    game = save_texture(ALBEDO, rgba)
    game.filepath_raw = str(WORK / (ALBEDO + ".png"))
    game.save()
    bpy.data.images.remove(game)
    material = bpy.data.materials.new(SLOT)
    material.use_nodes = True
    tree = material.node_tree
    shader = tree.nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = .88
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.image = preview
    tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
    tree.nodes.active = tex
    return material


def cape_weights(point, body, surface, triangles):
    upper_back = ease(105, 142, point.z)
    attachment = ease(133, 151, point.z) * (1 - .55 * ease(10, 22, point.y))
    result = defaultdict(float, {"spine_02": (1 - upper_back) * (1 - attachment),
                                 "spine_03": upper_back * (1 - attachment)})
    if attachment:
        hit, _, index, _ = surface.find_nearest(point)
        vertices = [body.data.vertices[i] for i in triangles[index]]
        basis = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        shares = barycentric_transform(hit, *(vertex.co for vertex in vertices), *basis)
        for vertex, share in zip(vertices, shares, strict=True):
            for group in vertex.groups:
                result[body.vertex_groups[group.group].name] += max(0, share) * group.weight * attachment
    largest = sorted(result.items(), key=lambda item: item[1], reverse=True)[:4]
    total = sum(weight for _, weight in largest)
    return {bone: weight / total for bone, weight in largest if weight > 0}


def collision_shape(armature, bone, start, end, radius_start, radius_end):
    frame = sifu.bl_to_ue(armature.data.bones[bone].matrix_local)
    start, end = (frame.inverted() @ (sifu.C3 @ Vector(point)) for point in (start, end))
    axis = end - start
    orientation = Vector((0, 0, 1)).rotation_difference(axis.normalized())
    return {"bone": bone, "type": "tapered", "center": list((start + end) / 2),
            "quat": [orientation.x, orientation.y, orientation.z, orientation.w],
            "radius0": radius_end, "radius1": radius_start, "length": axis.length}


def cloth_spec(armature):
    shapes = [
        ("spine_03", (0, 4, 125), (0, 4, 141), 14.5, 14),
        ("spine_02", (0, 4, 105), (0, 4, 122), 15, 14.5),
        ("pelvis", (-7, 4.5, 90), (7, 4.5, 90), 13.5, 13.5),
    ]
    for side, sign in (("l", 1), ("r", -1)):
        shapes.extend((
            (f"thigh_{side}", (sign * 12, 2, 79), (sign * 13.5, -6, 55), 14, 13),
            (f"calf_{side}", (sign * 14, -7, 49), (sign * 16, 0, 20), 12, 8),
            (f"upperarm_{side}", (sign * 22, 4, 138), (sign * 32, 7, 124), 8, 7),
        ))
    damping = dict.fromkeys("XYZ", .20)
    inertia = dict.fromkeys("XYZ", .8)
    return {
        "max_distance": MAX_DISTANCE, "render_slot": SLOT, "proxy_slot": PROXY_SLOT,
        "physics": {"bodies": [collision_shape(armature, *shape) for shape in shapes], "constraints": False},
        "config": {"Damping": damping, "LinearDrag": dict.fromkeys("XYZ", .16),
                   "AngularDrag": damping, "LinearInertiaScale": inertia,
                   "AngularInertiaScale": inertia, "CentrifugalInertiaScale": inertia,
                   "BendConstraint": {"Stiffness": .35}, "ShearConstraint": {"Stiffness": .75},
                   "StiffnessFrequency": 60, "SolverFrequency": 240, "CollisionThickness": 1.1},
    }


def simulation_proxy(cape):
    proxy = cape.copy()
    proxy.data = cape.data.copy()
    proxy.name = "Cape cloth simulation surface"
    proxy.modifiers.new("Sifu skeleton", "ARMATURE").object = cape.parent
    bpy.context.collection.objects.link(proxy)
    material = bpy.data.materials.new(PROXY_SLOT)
    proxy.data.materials[0] = material
    colors = proxy.data.color_attributes.new(name="ClothMask", type="BYTE_COLOR", domain="POINT")
    proxy.data.color_attributes.active_color = colors
    for vertex, data in zip(proxy.data.vertices, colors.data, strict=True):
        # The entire collar is pinned. The upper back eases into the hanging panel.
        travel = (1 - ease(42, 143, vertex.co.z)) ** 1.45
        data.color_srgb = (travel, 0, 0, 1)
    return proxy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloth", action="store_true", help="Extend the hem and export the NvCloth simulation surface")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    global WORK
    if args.cloth:
        WORK = WORK.with_name("cloth")
    WORK.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(WORK.parent / "sirung/Nailoong-Tongji-Sirung.blend"), load_ui=False)
    body = bpy.data.objects["SK_Nailoong"]
    hat = bpy.data.objects["SIRUNG Conical Hat"]
    arm = bpy.data.objects["Armature"]
    data = import_cape()
    fit(data, body.data, args.cloth)
    data.materials.clear()
    data.materials.append(fabric())
    for face in data.polygons:
        face.use_smooth = True
    cape = bpy.data.objects.new("Karnage Cape", data)
    bpy.context.collection.objects.link(cape)
    cape.parent = arm
    body.data.calc_loop_triangles()
    triangles = [triangle.vertices[:] for triangle in body.data.loop_triangles]
    surface = BVHTree.FromPolygons([vertex.co for vertex in body.data.vertices], triangles, all_triangles=True)
    if args.cloth:
        torso_bones = {group.index for group in body.vertex_groups
                       if group.name.startswith(("spine", "pelvis", "neck", "head"))}
        torso_vertices = [sum(weight.weight for weight in vertex.groups if weight.group in torso_bones) > .5
                          for vertex in body.data.vertices]
        torso = BVHTree.FromPolygons([vertex.co for vertex in body.data.vertices],
                                    [tri for tri in triangles if any(torso_vertices[i] for i in tri)],
                                    all_triangles=True)
        fit_back_panel(data, torso)
    groups = {}
    for vertex in data.vertices:
        for bone, weight in cape_weights(vertex.co, body, surface, triangles).items():
            if bone not in groups:
                groups[bone] = cape.vertex_groups.new(name=bone)
            groups[bone].add([vertex.index], weight, "REPLACE")
    proxy = simulation_proxy(cape) if args.cloth else None
    select(cape)
    lining = cape.modifiers.new("Cloth lining", "SOLIDIFY")
    lining.thickness = .24
    lining.offset = 0
    bpy.ops.object.modifier_apply(modifier=lining.name)
    cape.modifiers.new("Sifu skeleton", "ARMATURE").object = arm
    cape["Source"] = "Cape by Karnage (Ring1), CC BY 4.0"
    cape["Source URL"] = "https://sketchfab.com/3d-models/cape-61e185ae00b640258071c581ab40f749"
    assert all(1 <= len(vertex.groups) <= 4 and abs(sum(g.weight for g in vertex.groups) - 1) < .0001
               for vertex in cape.data.vertices)
    bpy.context.preferences.filepaths.save_version = 0
    name = "Nailoong-Tongji-Sirung-LongCape" if args.cloth else "Nailoong-Tongji-Sirung-Cape"
    if proxy:
        proxy.hide_set(True)
        proxy.hide_render = True
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK / (name + ".blend")))
    export = [arm, body, hat, cape]
    if proxy:
        proxy.hide_set(False)
        proxy.hide_render = False
        export.append(proxy)
        (WORK / "cloth.json").write_text(json.dumps(cloth_spec(arm), indent=2), encoding="utf-8")
    sifu.export_fbx(str(WORK / "SK_Nailoong_Tongji.fbx"), export)


if __name__ == "__main__":
    main()

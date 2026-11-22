"""Fit and export Nailoong's two-material Wanderer outfit in scene centimetres."""

import argparse
import json
import sys
from math import cos, pi, sin
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, ROOT, sifu
from preview_model import pose

WORK = ROOT / "build/wanderer"
COLOR = "T_Nailoong_Wanderer_BaseColor"
SLOT = "M_Nailoong_Wanderer"
NAME = "SK_Nailoong_Wanderer"


def straw_grain(source, u, v):
    objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(source))
    image = bpy.data.images["straw-hat_body_basecolor"]
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    # The upper-left island in the CC0 albedo is the unadorned woven brim.
    radius = .092 + .096 * v
    x = ((.206 + radius * cos_grid(u, 1)) * width).astype(int)
    y = ((.791 + radius * sin_grid(u, 1)) * height).astype(int)
    grain = pixels[y, x, :3].mean(axis=2)
    for obj in set(bpy.data.objects) - objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    return 1.25 * (grain - np.median(grain)).clip(-.055, .055)


def atlas(source):
    size = 1024
    half = size // 2
    u, v = np.meshgrid(np.linspace(0, 1, half), np.linspace(0, 1, half))
    rng = np.random.default_rng(15)
    fabric = rng.normal(0, .008, u.shape) + .013 * sin_grid(u, 132) * sin_grid(v, 145)
    fold = .030 * sin_grid(u + .016 * cos_grid(v, 1), 5)
    cape = np.array([.106, .265, .218]) + (fabric + fold)[..., None]
    distance = np.minimum(np.minimum(u, 1 - u), v * .8)
    border = ((distance > .008) & (distance < .027)) | ((distance > .038) & (distance < .044))
    cape[border] = np.array([.43, .45, .26]) + fabric[border, None]
    bamboo = (.037 * cos_grid(v, 28) + .019 * cos_grid(u + .01 * sin_grid(v, 28), 119)
              + .012 * cos_grid(u + v, 51) + fabric)
    if source:
        bamboo += straw_grain(source, u, v)
    hat = np.array([.79, .626, .386]) + bamboo[..., None]
    rim = v > .94
    hat[rim] = np.array([.31, .225, .115]) + bamboo[rim, None]
    metal = np.array([.75, .491, .233]) + (.08 * sin_grid(u, 1) + fabric)[..., None]
    cord = np.array([.225, .289, .193]) + (.036 * sin_grid(u + v, 8) + fabric)[..., None]
    pixels = np.ones((size, size, 4), dtype=np.float32)
    pixels[:half, :half, :3], pixels[:half, half:, :3] = cape, hat
    pixels[half:, :half, :3], pixels[half:, half:, :3] = metal, cord
    pixels = pixels.clip(0, 1)
    preview = bpy.data.images.new(COLOR + "_Preview", size, size, alpha=False)
    preview.pixels.foreach_set(pixels.ravel())
    preview.pack()
    game = bpy.data.images.new(COLOR, size, size, alpha=True)
    game.alpha_mode = "CHANNEL_PACKED"
    pixels[:, :, 3] = 0
    game.pixels.foreach_set(pixels.ravel())
    game.filepath_raw = str(WORK / (COLOR + ".png"))
    game.file_format = "PNG"
    game.save()
    bpy.data.images.remove(game)
    mat = bpy.data.materials.new(SLOT)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = preview
    nodes.active = tex
    shader = nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = .78
    mat.node_tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
    return mat


def sin_grid(values, cycles):
    return np.sin(2 * pi * cycles * values)


def cos_grid(values, cycles):
    return np.cos(2 * pi * cycles * values)


def tile(u, v, column=0, row=0):
    return (.5 * column + .002 + .496 * u, .5 * row + .002 + .496 * v)


def mesh(name, points, faces, uv, arm, material, weights):
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, [], faces)
    data.update()
    layer = data.uv_layers.new(name="OutfitUV")
    for poly, coords in zip(data.polygons, uv, strict=True):
        poly.use_smooth = True
        for index, coord in zip(poly.loop_indices, coords, strict=True):
            layer.data[index].uv = coord
    data.materials.append(material)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    groups = {}
    for vertex in data.vertices:
        for bone, value in weights(vertex.co).items():
            if value <= .00001:
                continue
            if bone not in groups:
                groups[bone] = obj.vertex_groups.new(name=bone)
            groups[bone].add([vertex.index], value, "REPLACE")
    modifier = obj.modifiers.new("Sifu skeleton", "ARMATURE")
    modifier.object = arm
    return obj


def hat(arm, mat):
    # Closed cross-section, with a shallow cone and a recessed lower crown.
    profile = ((.04, 194), (.18, 192.5), (.32, 189.4), (.49, 185.2),
               (.66, 180.4), (.83, 175.7), (.94, 172.7), (.99, 171.8),
               (1, 171.4), (.998, 170.6), (.97, 170.3), (.92, 171.6),
               (.73, 176.1), (.45, 182.8), (.15, 188.3), (.04, 189.2))
    count = 96
    points = []
    for radius, height in profile:
        for j in range(count):
            angle = 2 * pi * j / count
            depth = 30 * radius * sin(angle)
            points.append((33 * radius * cos(angle), depth - 3,
                           height - 2.1 - 3.7 * radius + .055 * depth + .15 * radius * cos(8 * angle)))
    faces, uv = [], []
    for ring, ((r0, _), (r1, _)) in enumerate(zip(profile, profile[1:])):
        for j in range(count):
            k = (j + 1) % count
            faces.append((ring * count + j, (ring + 1) * count + j,
                          (ring + 1) * count + k, ring * count + k))
            a, b = j / count, (j + 1) / count
            uv.append([tile(i, r, 1) for i, r in ((a, r0), (a, r1), (b, r1), (b, r0))])
    faces.extend((tuple(range(count)), tuple(reversed(range(len(points) - count, len(points))))))
    uv.extend([[tile(j / count, 0, 1) for j in range(count)]] * 2)
    return mesh("Bamboo hat", points, faces, uv, arm, mat, lambda x: {"head": 1})


def ease(low, high, value):
    t = min(1, max(0, (value - low) / (high - low)))
    return t * t * (3 - 2 * t)


def cape_weights(point):
    levels = (91, 108, 124, 148)
    bones = ("pelvis", "spine_01", "spine_02", "spine_03")
    z, width = point.z, abs(point.x)
    index = min(len(levels) - 2, max(0, int(np.searchsorted(levels, z)) - 1))
    blend = ease(levels[index], levels[index + 1], z)
    side = "l" if point.x > 0 else "r"
    shoulder = .52 * ease(14, 35, width) * ease(93, 117, z) * (1 - ease(135, 153, z))
    hem = .43 * ease(2, 17, width) * (1 - ease(75, 97, z))
    core = 1 - shoulder - hem
    return {bones[index]: core * (1 - blend), bones[index + 1]: core * blend,
            f"upperarm_{side}": shoulder, f"thigh_{side}": hem}


def cape(arm, mat):
    width, height = 48, 48
    points, faces, uvs = [], [], []
    # The shoulder flare starts underneath the clasp and opens around the back.
    # Lower rows arc further behind the hips to clear long strides.
    for v in np.linspace(0, 1, height + 1):
        reach = 16 + 26 * sin(pi * v / 2) ** .56 - 5 * v ** 3
        depth = 21 + 19 * sin(pi * v / 2) ** .95
        for u in np.linspace(-1, 1, width + 1):
            x = u * reach
            z = 154 - 110 * v - 3.2 * abs(u) ** 1.6 * (1 - v) + 6 * u ** 2 * v ** 3
            y = (depth + (3.3 - 8 * v) * u ** 2
                 + (1.1 + 1.25 * v) * cos(5.8 * pi * u + v))
            points.append((x, y, z))
    stride = width + 1
    for j in range(height):
        for i in range(width):
            k = j * stride + i
            corners = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
            faces.append((k, k + 1, k + stride + 1, k + stride))
            uvs.append([tile(u / width, 1 - v / height) for u, v in corners])
    obj = mesh("Forest green cape", points, faces, uvs, arm, mat, cape_weights)
    obj.modifiers.new("Woven fabric thickness", "SOLIDIFY").thickness = .42
    return obj


def tube(name, line, radius, arm, mat, column, weights):
    sides = 10
    points, faces, uv = [], [], []
    path = [Vector(p) for p in line]
    for i, center in enumerate(path):
        direction = (path[min(i + 1, len(path) - 1)] - path[max(0, i - 1)]).normalized()
        reference = Vector((0, 0, 1)) if column else Vector((0, 1, 0))
        axis = direction.cross(reference).normalized()
        side = direction.cross(axis).normalized()
        for j in range(sides):
            a = 2 * pi * j / sides
            points.append(center + radius * (cos(a) * axis + sin(a) * side))
    for i in range(len(path) - 1):
        for j in range(sides):
            k = (j + 1) % sides
            faces.append((i * sides + j, i * sides + k, (i + 1) * sides + k, (i + 1) * sides + j))
            uv.append([tile(u / sides, v / (len(path) - 1), column, 1)
                       for u, v in ((j, i), (j + 1, i), (j + 1, i + 1), (j, i + 1))])
    return mesh(name, points, faces, uv, arm, mat, weights)


def clasp(arm, mat, body):
    data = body.data
    tree = BVHTree.FromPolygons([v.co for v in data.vertices], [p.vertices[:] for p in data.polygons])
    groups = {g.index: g.name for g in body.vertex_groups}

    def chest_weights(point):
        if point.y > 15:
            return {"spine_03": 1}
        _, _, polygon, _ = tree.find_nearest(point)
        vertex = min((data.vertices[i] for i in data.polygons[polygon].vertices),
                     key=lambda v: (point - v.co).length_squared)
        return {groups[g.group]: g.weight for g in vertex.groups}

    clasp_weights = chest_weights(Vector((0, -25.5, 142.8)))
    for side in (-1, 1):
        path = [(side * x, y, z) for x, y, z in (
            (15.1, 23.5, 151.4), (19, 18, 154.4), (20.1, 7, 155.4),
            (20.0, -4, 154.3), (17.4, -14.3, 149.4), (12, -20.4, 146.1),
            (6.8, -23.2, 143.9), (2.9, -25.1, 142.8))]
        curve = []
        for i in range(len(path) - 1):
            p0, p1, p2, p3 = map(Vector, (path[max(0, i - 1)], path[i], path[i + 1],
                                            path[min(len(path) - 1, i + 2)]))
            for t in (.0, .25, .5, .75):
                curve.append(.5 * ((2 * p1) + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                                   + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
        tube("Braided collar tie", [*curve, path[-1]], .66, arm, mat, 1, chest_weights)
    for radius, y, stroke in ((2.85, -25.35, .63), (1.35, -25.87, .37)):
        line = [(radius * cos(a), y, 142.8 + radius * sin(a)) for a in np.linspace(0, 2 * pi, 29)]
        tube("Antique brass clasp", line, stroke, arm, mat, 0, lambda point: clasp_weights)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hat", type=Path, help="Optional Grab3D Straw Hat GLB.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    WORK.mkdir(exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "Nailoong-RoundBack.blend"), load_ui=False)
    arm = bpy.data.objects["Armature"]
    body = bpy.data.objects["SK_Nailoong"]
    assert len(arm.data.bones) == 273 and len(body.material_slots) == 1
    material = atlas(args.hat)
    hat(arm, material)
    cape(arm, material)
    clasp(arm, material, body)
    outfit = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj != body]
    pose(arm, None)
    for obj in [body, *outfit]:
        assert all(1 <= len(v.groups) <= 4 and abs(sum(g.weight for g in v.groups) - 1) < .0001
                   for v in obj.data.vertices), obj.name
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK / "Nailoong-Wanderer.blend"))
    sifu.export_fbx(str(WORK / (NAME + ".fbx")), [arm, body, *outfit])
    cape_mesh = bpy.data.objects["Forest green cape"].data
    band = [v.co for v in cape_mesh.vertices]
    brim = min(bpy.data.objects["Bamboo hat"].data.vertices, key=lambda v: v.co.y).co
    (WORK / "fit.json").write_text(json.dumps({
        "base": "Nailoong-RoundBack.blend", "bones": len(arm.data.bones),
        "hat_albedo_detail": args.hat.name if args.hat else "procedural",
        "front_brim_height_cm": round(brim.z, 2),
        "cape_width_cm": round(max(v.x for v in band) - min(v.x for v in band), 2),
        "cape_hem_height_cm": round(min(v.z for v in band), 2),
        "body_vertices": len(body.data.vertices), "garment_vertices": {o.name: len(o.data.vertices) for o in outfit},
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

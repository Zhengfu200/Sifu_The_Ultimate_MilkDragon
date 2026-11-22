"""Bake and skin the local Nailoong source for the Epic Sifu male skeleton."""

import json
import sys
from collections import Counter
from heapq import heappop, heappush
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tools/GameModdingKnowledge/portable-kits/sifu/scripts/blender"
sys.path.insert(0, str(SUPPORT))
import sifu_common as sifu
sys.path.insert(0, str(ROOT / "scripts"))
from fit_reference import ReferenceFit


OUT = ROOT / "build/model"
REFERENCE = ROOT / "local/reference/Sifu/Content/Characters/MainChar/M/Meshes"
SKELETON = REFERENCE / "SK_M_MainChar_01.SK_M_MainChar_01.skel.json"

# Landmarks in the source mesh's local coordinate system. It faces +Y.
ARM = ((.30, -.06, .28), (.413, -.06, .115), (.397, .025, -.175))
LEG = ((.205, -.035, -.31), (.227, -.075, -.60), (.246, -.135, -.86), (.26, .035, -.943))
TORSO = (
    (-.30, "pelvis"), (-.16, "spine_01"), (.04, "spine_02"),
    (.28, "spine_03"), (.49, "neck_01"), (.55, "neck_02"), (.66, "head"),
)


def select(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def bake_color(obj, path):
    select(obj)
    obj.data.uv_layers.new(name="NailoongAtlas", do_init=False)
    obj.data.uv_layers.active = obj.data.uv_layers[-1]
    obj.data.uv_layers[-1].active_render = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=.012)
    bpy.ops.object.mode_set(mode="OBJECT")

    image = bpy.data.images.new("T_Nailoong_BaseColor", width=2048, height=2048, alpha=True)
    for material in obj.data.materials:
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        shader = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        output = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
        emission = nodes.new("ShaderNodeEmission")
        color = shader.inputs["Base Color"]
        if color.is_linked:
            links.new(color.links[0].from_socket, emission.inputs["Color"])
        else:
            emission.inputs["Color"].default_value = color.default_value
        links.new(emission.outputs[0], output.inputs["Surface"])
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        nodes.active = texture

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    bpy.ops.object.bake(type="EMIT", margin=8)
    # The game's clothing shader reads the base-color alpha as a mask.
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels[3::4] = 0
    game_image = bpy.data.images.new("Nailoong game base color", 2048, 2048, alpha=True)
    game_image.alpha_mode = "CHANNEL_PACKED"
    game_image.pixels.foreach_set(pixels)
    game_image.filepath_raw = str(path)
    game_image.file_format = "PNG"
    game_image.save()
    bpy.data.images.remove(game_image)
    # The editor preview keeps full opacity and embeds its own copy.
    image.pack()
    for suffix, rgba in (("Combo", (205 / 255, 0, 1, 1)), ("Normal", (128 / 255, 128 / 255, 1, 1))):
        auxiliary = bpy.data.images.new("Nailoong " + suffix, 16, 16, alpha=True)
        auxiliary.colorspace_settings.name = "Non-Color"
        auxiliary.pixels.foreach_set(rgba * (16 * 16))
        auxiliary.filepath_raw = str(path.with_name("T_Nailoong_" + suffix + ".png"))
        auxiliary.file_format = "PNG"
        auxiliary.save()
        bpy.data.images.remove(auxiliary)

    material = bpy.data.materials.new("M_Nailoong")
    material.use_nodes = True
    shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    shader.inputs["Roughness"].default_value = .72
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    material.node_tree.nodes.active = texture
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for layer in list(obj.data.uv_layers):
        if layer.name != "NailoongAtlas":
            obj.data.uv_layers.remove(layer)


def smooth(lo, hi, v):
    t = min(1.0, max(0.0, (v - lo) / (hi - lo)))
    return t * t * (3 - 2 * t)


def along(points, coordinate):
    for (lo, a), (hi, b) in zip(points, points[1:]):
        if coordinate <= hi:
            blend = smooth(lo, hi, coordinate)
            return {a: 1 - blend, b: blend}
    return {points[-1][1]: 1.0}


def arm_regions(mesh):
    points = [vertex.co for vertex in mesh.vertices]
    edges = [[] for _ in points]
    for edge in mesh.edges:
        a, b = edge.vertices
        length = (points[a] - points[b]).length
        edges[a].append((b, length))
        edges[b].append((a, length))

    def distances(seeds):
        distance = [float("inf")] * len(points)
        queue = [(0.0, i) for i in seeds]
        for _, i in queue:
            distance[i] = 0.0
        while queue:
            step, i = heappop(queue)
            if step != distance[i]:
                continue
            for j, length in edges[i]:
                candidate = step + length
                if candidate < distance[j]:
                    distance[j] = candidate
                    heappush(queue, (candidate, j))
        return distance

    # Below the armpits the arms and torso form three disconnected regions.
    # Seed the whole arm, not just fingertips: fingertip-only seeds incorrectly
    # classified most of the upper arm as torso in the first version.
    allowed = {i for i, p in enumerate(points) if -.30 < p.z < .23}
    arm_seeds, torso_seeds = set(), set()
    while allowed:
        first = allowed.pop()
        component, pending = {first}, [first]
        while pending:
            i = pending.pop()
            for j, _ in edges[i]:
                if j in allowed:
                    allowed.remove(j)
                    component.add(j)
                    pending.append(j)
        if any(abs(points[i].x) > .365 and points[i].z < -.16 for i in component):
            arm_seeds.update(component)
        else:
            torso_seeds.update(component)
    torso_seeds.update(i for i, (x, y, z) in enumerate(points)
                       if abs(x) < .14 or abs(y) > .22 or z > .51 or z < -.31)
    hands = distances(arm_seeds)
    body = distances(torso_seeds)
    return [smooth(-.18, .18, b - a) if a < float("inf") else 0.0 for a, b in zip(hands, body)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "source/nailoong/nailong_colored.blend"), load_ui=False)
    (obj,) = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    obj.name = "SK_Nailoong"
    bpy.context.preferences.filepaths.save_version = 0
    bake_color(obj, OUT / "T_Nailoong_BaseColor.png")
    sifu.setup_cm_scene()
    floor = min(vertex.co.z for vertex in obj.data.vertices)
    scale = 97.0

    def transform(source):
        return Vector((-source.x * scale, -source.y * scale, (source.z - floor) * scale))

    bones = sifu.load_skel(str(SKELETON))
    world = {name: sifu.ue_to_bl(matrix) for name, matrix in sifu.ue_world(bones).items()}
    armature = sifu.build_armature("Armature", bones, world)
    fit = ReferenceFit(world, transform, ARM, LEG, TORSO)
    obj.location = (0, 0, 0)
    groups = {bone["name"]: obj.vertex_groups.new(name=bone["name"]) for bone in bones}
    usage = Counter()
    arm_mask = arm_regions(obj.data)
    for vertex in obj.data.vertices:
        arm = arm_mask[vertex.index]
        point, influences = fit.vertex(vertex.co.copy(), arm)
        influences = {name: w for name, w in influences.items() if w > 1e-5}
        total = sum(influences.values())
        if total <= 0 or len(influences) > 4:
            raise RuntimeError(f"Invalid weights on vertex {vertex.index}")
        for name, weight in influences.items():
            groups[name].add([vertex.index], weight / total, "REPLACE")
            usage[name] += 1
        vertex.co = point

    # Relax the fitted shoulder transition and limb cross sections. The source
    # topology already has sufficient elbow/wrist loops; avoid subdividing it.
    neighbours = [[] for _ in obj.data.vertices]
    for edge in obj.data.edges:
        a, b = edge.vertices
        neighbours[a].append(b)
        neighbours[b].append(a)
    relax = [1.0 if .005 < a < .995 else .06 if a >= .995 else 0.0 for a in arm_mask]
    for _ in range(3):
        relax = [max(relax[i], max((relax[j] * .6 for j in ns), default=0)) for i, ns in enumerate(neighbours)]
    for _ in range(90):
        points = [v.co.copy() for v in obj.data.vertices]
        for i, ns in enumerate(neighbours):
            if ns and relax[i] > .01:
                average = sum((points[j] for j in ns), Vector()) / len(ns)
                obj.data.vertices[i].co = points[i].lerp(average, .38 * relax[i])

    obj.parent = armature
    modifier = obj.modifiers.new("Sifu skeleton", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = False
    obj.data.update()
    select(obj)
    bpy.context.scene.render.engine = "BLENDER_EEVEE"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.clip_end = 5000
                area.spaces.active.shading.color_type = "TEXTURE"
                area.spaces.active.region_3d.view_distance = 240
                area.spaces.active.region_3d.view_location = (0, 0, 86)

    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-Sifu.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong.fbx"), [armature, obj])
    summary = {"revision": "original-reference-arm-fix-v2", "vertices": len(obj.data.vertices),
               "reference_bones": len(bones), "weighted_bones": dict(usage),
               "preserve_volume": False, "reference_pose": "unmodified SK_M_MainChar_01"}
    (OUT / "model-report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

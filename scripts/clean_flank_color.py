"""Clean the stray claw pigment from the abdomen's existing UV atlas."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, select, sifu
from shorten_leg_silhouette import coordinates, influence, smooth

# Linear color constants from the original 'yellow' Blender material.
YELLOW = np.array((1.0, .613275647, .040441278), dtype=np.float32)
CLAW = np.array((.109142810, .069446608, .033121254), dtype=np.float32)
BELLY = np.array((.758380115, .503417015, .248164296), dtype=np.float32)
PALETTE = np.stack((CLAW - YELLOW, BELLY - YELLOW))


def pixels(image):
    data = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(data)
    return data.reshape(-1, 4)


def linear(rgb):
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def srgb(rgb):
    rgb = rgb.clip(0, 1)
    return np.where(rgb <= .0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - .055)


def flank_weights(mesh):
    x, _, z = coordinates(mesh.data).T
    arms = influence(mesh, ("upperarm", "lowerarm", "hand_"))
    legs = influence(mesh, ("thigh_", "calf_", "foot_", "ball_"))
    return (smooth(69, 77, z) * (1 - smooth(108, 133, z))
            * smooth(12, 21, np.abs(x)) * (1 - smooth(.10, .50, arms))
            * (1 - smooth(.60, .97, legs)))


def repack_atlas(mesh, image_node):
    """Separate overlapping UVs on the current mesh and transfer its old colors."""
    old_uv = mesh.data.uv_layers.active
    old_uv.name = "LegacyAtlas"
    new_uv = mesh.data.uv_layers.new(name="NailoongAtlas", do_init=False)
    mesh.data.uv_layers.active = new_uv
    new_uv.active_render = True
    select(mesh)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=.75, island_margin=.012)
    bpy.ops.object.mode_set(mode="OBJECT")

    tree = mesh.data.materials[0].node_tree
    coords = tree.nodes.new("ShaderNodeUVMap")
    coords.uv_map = "LegacyAtlas"
    tree.links.new(coords.outputs["UV"], image_node.inputs["Vector"])
    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(image_node.outputs["Color"], emission.inputs["Color"])
    output = next(node for node in tree.nodes if node.type == "OUTPUT_MATERIAL")
    shader = output.inputs["Surface"].links[0].from_socket
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    size = tuple(image_node.image.size)
    target = bpy.data.images.new("Transfer original colors", *size, alpha=True)
    bake = tree.nodes.new("ShaderNodeTexImage")
    bake.image = target
    tree.nodes.active = bake
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    bpy.ops.object.bake(type="EMIT", margin=6, margin_type="EXTEND")

    tree.links.new(shader, output.inputs["Surface"])
    for node in (coords, emission, bake):
        tree.nodes.remove(node)
    tree.nodes.active = image_node
    mesh.data.uv_layers.remove(mesh.data.uv_layers["LegacyAtlas"])
    scene.render.engine = "BLENDER_EEVEE"
    return target


def raster_mask(mesh, size):
    """Map the repair to exact UV triangles and extend it to island padding."""
    uv = mesh.data.uv_layers.active
    assert uv.name == "NailoongAtlas" and uv.active_render
    values = flank_weights(mesh)
    mesh.data.calc_loop_triangles()
    coords = np.array([loop.uv[:] for loop in uv.data]) * size
    mask = np.zeros((size[1], size[0]), dtype=np.float32)
    covered = np.zeros_like(mask, dtype=bool)
    protected = np.zeros_like(mask, dtype=bool)
    for triangle in mesh.data.loop_triangles:
        corners = coords[list(triangle.loops)]
        weights = values[list(triangle.vertices)]
        left, bottom = np.maximum(0, np.floor(corners.min(axis=0)).astype(int))
        right, top = np.minimum(size, np.floor(corners.max(axis=0)).astype(int) + 1)
        if left >= right or bottom >= top:
            continue
        a, b = corners[1:] - corners[0]
        determinant = a[0] * b[1] - a[1] * b[0]
        if abs(determinant) < 1e-7:
            continue
        yy, xx = np.ogrid[bottom:top, left:right]
        rx = xx + .5 - corners[0, 0]
        ry = yy + .5 - corners[0, 1]
        p = (rx * b[1] - ry * b[0]) / determinant
        q = (a[0] * ry - a[1] * rx) / determinant
        inside = (p >= -1e-6) & (q >= -1e-6) & (p + q <= 1 + 1e-6)
        covered[bottom:top, left:right] |= inside
        if weights.max() < .001:
            protected[bottom:top, left:right] |= inside
            continue
        value = weights[0] * (1 - p - q) + weights[1] * p + weights[2] * q
        area = mask[bottom:top, left:right]
        area[inside] = np.maximum(area[inside], value[inside])
    overlap = int(np.count_nonzero(protected & (mask > .5)))
    for _ in range(6):
        padded = np.pad(mask, 1)
        extent = np.maximum.reduce((padded[:-2, 1:-1], padded[2:, 1:-1],
                                    padded[1:-1, :-2], padded[1:-1, 2:]))
        mask[~covered] = np.maximum(mask[~covered], extent[~covered])
    mask[protected] = 0
    return mask.ravel(), overlap


def sample_faces(mesh, size, mask, changed):
    """Check that edits don't touch any face centers outside the flank region."""
    uv = mesh.data.uv_layers.active.data
    ownership = flank_weights(mesh)
    report = {"repaired_flank_faces": 0, "protected_face_centers_changed": 0}
    for face in mesh.data.polygons:
        ids = list(face.vertices)
        u, v = np.mean([uv[i].uv[:] for i in face.loop_indices], axis=0)
        row = int(np.clip(v * size[1], 0, size[1] - 1))
        col = int(np.clip(u * size[0], 0, size[0] - 1))
        i = row * size[0] + col
        if changed[i]:
            if ownership[ids].max() < .001 or mask[i] < .001:
                report["protected_face_centers_changed"] += 1
            else:
                report["repaired_flank_faces"] += 1
    return report


def main():
    mesh = bpy.data.objects["SK_Nailoong"]
    material = mesh.data.materials[0]
    image_node = next(n for n in material.node_tree.nodes if n.type == "TEX_IMAGE")
    original = repack_atlas(mesh, image_node)
    size = tuple(original.size)
    mask, overlapping_texels = raster_mask(mesh, size)
    if overlapping_texels > 10:
        raise RuntimeError(f"The new layout has {overlapping_texels} texels shared with protected faces")
    base = pixels(original)
    changed = base.copy()
    region = np.flatnonzero(mask > .001)
    colors = linear(base[region, :3])
    part = (colors - YELLOW) @ np.linalg.pinv(PALETTE)
    residual = np.linalg.norm(colors - YELLOW - part @ PALETTE, axis=1)
    # The original shader blends body yellow, claw brown, and belly tan.
    # Remove only the brown coefficient and keep the beige blend intact.
    pigment = part[:, 0].clip(0, 1) * (1 - smooth(.025, .075, residual))
    clean = colors - (pigment * mask[region])[:, None] * PALETTE[0]
    changed[region, :3] = srgb(clean)
    difference = np.max(np.abs(changed[:, :3] - base[:, :3]), axis=1) > 1 / 255
    report = sample_faces(mesh, size, mask, difference)
    if report["repaired_flank_faces"] < 30 or report["protected_face_centers_changed"]:
        raise RuntimeError(f"Unexpected texture coverage: {report}")

    preview = bpy.data.images.new("T_Nailoong_BaseColor_CleanFlanks", *size, alpha=True)
    preview.pixels.foreach_set(changed.ravel())
    preview.file_format = "PNG"
    preview.pack()
    image_node.image = preview
    bpy.data.images.remove(original)
    game = bpy.data.images.new("Clean flank game texture", *size, alpha=True)
    game.alpha_mode = "CHANNEL_PACKED"
    changed[:, 3] = 0
    game.pixels.foreach_set(changed.ravel())
    game.filepath_raw = str(OUT / "T_Nailoong_BaseColor_CleanFlanks.png")
    game.file_format = "PNG"
    game.save()
    bpy.data.images.remove(game)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "Nailoong-CleanFlanks.blend"))
    sifu.export_fbx(str(OUT / "SK_Nailoong-clean-flanks.fbx"), [mesh.parent, mesh])
    report.update({"edited_texels": int(difference.sum()), "atlas_size": size,
                   "overlap_with_protected_islands_texels": overlapping_texels,
                   "source": "Shared flank and claw texels in the previous UV atlas"})
    (OUT / "flank-cleanup-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

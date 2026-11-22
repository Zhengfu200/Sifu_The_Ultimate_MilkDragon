"""Paint the Tongji outfit on the v14 mesh's existing game UVs."""

import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_model import OUT, sifu
from clean_flank_color import pixels
from shorten_leg_silhouette import smooth


WORK = OUT.parent / "tongji"
BADGE = OUT.parents[1] / "source/nailoong/skins/tongji/Tongji-University-badge.png"
TEXTURE = "T_Nailoong_Tongji_BaseColor"
SKY_BLUE = np.array((37, 136, 205)) / 255
IVORY = np.array((247, 250, 253)) / 255
SEAL_BLUE = np.array((0, 89, 171)) / 255


def seal_opacity(mask, x, z):
    # Front projection in the reference pose, centered above the widest part of the belly.
    height, width = mask.shape
    u = (x / 22.8 + .5) * width - .5
    v = ((z - 111) / 22.8 + .5) * height - .5
    inside = (u >= 0) & (u < width - 1) & (v >= 0) & (v < height - 1)
    opacity = np.zeros_like(x)
    left, bottom = u[inside].astype(int), v[inside].astype(int)
    dx, dy = u[inside] - left, v[inside] - bottom
    opacity[inside] = ((1 - dy) * ((1 - dx) * mask[bottom, left] + dx * mask[bottom, left + 1])
                       + dy * ((1 - dx) * mask[bottom + 1, left] + dx * mask[bottom + 1, left + 1]))
    return opacity


def paint(source, points, seal):
    x, y, z = points.T
    red, green, blue = source.T
    # Use the default Nailoong belly marking as the boundary for the white patch.
    belly = ((blue - 57 / 255) / ((136 - 57) / 255)).clip(0, 1)
    belly *= smooth(-.03, .08, red - green) * (1 - smooth(138, 143, z))
    white = belly[:, None]
    color = SKY_BLUE * (1 - white) + IVORY * white

    eye = smooth(-.11, .15, green - red) * smooth(162, 165, z) * smooth(.35, .70, green)
    iris = np.array((113, 198, 231)) / 255
    color = color * (1 - eye[:, None]) + iris * eye[:, None]
    face = smooth(153, 156, z) * (1 - smooth(-8, -6, y))
    dark = (face * (1 - smooth(.12, .66, np.maximum(red, green))))[:, None]
    color = color * (1 - dark) + np.array((13, 24, 37)) / 255 * dark

    mark = (seal_opacity(seal, x, z) * (y < -29) * white[:, 0])[:, None]
    return color * (1 - mark) + SEAL_BLUE * mark


def paint_atlas(mesh, old, seal):
    height, width, _ = old.shape
    size = np.array((width, height))
    uv = np.array([loop.uv[:] for loop in mesh.uv_layers.active.data]) * size
    xyz = np.array([vertex.co[:] for vertex in mesh.vertices])
    result = np.ones_like(old)
    result[:, :, :3] = SKY_BLUE
    covered = np.zeros((height, width), dtype=bool)
    mesh.calc_loop_triangles()
    for triangle in mesh.loop_triangles:
        corners = uv[list(triangle.loops)]
        left, bottom = np.maximum(0, np.floor(corners.min(axis=0)).astype(int))
        right, top = np.minimum(size, np.floor(corners.max(axis=0)).astype(int) + 1)
        a, b = corners[1:] - corners[0]
        determinant = a[0] * b[1] - a[1] * b[0]
        if abs(determinant) < 1e-7 or left >= right or bottom >= top:
            continue
        yy, xx = np.ogrid[bottom:top, left:right]
        dx, dy = xx + .5 - corners[0, 0], yy + .5 - corners[0, 1]
        s = (dx * b[1] - dy * b[0]) / determinant
        t = (a[0] * dy - a[1] * dx) / determinant
        inside = (s >= -1e-6) & (t >= -1e-6) & (s + t <= 1 + 1e-6)
        if not inside.any():
            continue
        vertices = xyz[list(triangle.vertices)]
        points = (vertices[0] + s[inside, None] * (vertices[1] - vertices[0])
                  + t[inside, None] * (vertices[2] - vertices[0]))
        area = np.s_[bottom:top, left:right]
        result[area][inside, :3] = paint(old[area][inside, :3], points, seal)
        covered[area] |= inside

    # Extend the painted edges under bilinear sampling and lower mip levels.
    for _ in range(12):
        filled = covered.copy()
        for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
            edge = np.roll(covered, step, axis=axis) & ~filled
            rows, columns = np.nonzero(edge)
            source_rows = (rows - step) % height if axis == 0 else rows
            source_columns = (columns - step) % width if axis == 1 else columns
            result[rows, columns] = result[source_rows, source_columns]
            filled |= edge
        covered = filled
    return result


def save_texture(name, data):
    height, width, _ = data.shape
    image = bpy.data.images.new(name, width, height, alpha=True)
    image.alpha_mode = "CHANNEL_PACKED"
    image.pixels.foreach_set(data.ravel())
    image.update()
    image.file_format = "PNG"
    return image


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "Nailoong-RoundBack.blend"), load_ui=False)
    body = bpy.data.objects["SK_Nailoong"]
    armature = bpy.data.objects["Armature"]
    assert len(armature.data.bones) == 273 and len(body.material_slots) == 1
    material = body.data.materials[0]
    image_node = next(node for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
    old_image = image_node.image
    # Keep the thin lettering and double border legible in wardrobe close-ups.
    old_image.scale(4096, 4096)
    old = pixels(old_image).reshape(old_image.size[1], old_image.size[0], 4)
    badge = bpy.data.images.load(str(BADGE))
    badge.alpha_mode = "CHANNEL_PACKED"
    seal = pixels(badge)[:, 3].reshape(badge.size[1], badge.size[0])
    assert seal.min() == 0 and seal.max() == 1
    data = paint_atlas(body.data, old, seal)
    assert np.count_nonzero(np.max(np.abs(data[:, :, :3] - SEAL_BLUE), axis=2) < .001) > 800
    bpy.data.images.remove(badge)

    preview = save_texture(TEXTURE, data)
    preview.pack()
    image_node.image = preview
    bpy.data.images.remove(old_image)
    # The game material uses the base-color alpha as a mask. Match the v14 atlas.
    data[:, :, 3] = 0
    game = save_texture("Tongji game texture", data)
    game.filepath_raw = str(WORK / (TEXTURE + ".png"))
    game.save()
    bpy.data.images.remove(game)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK / "Nailoong-Tongji.blend"))
    sifu.export_fbx(str(WORK / "SK_Nailoong_Tongji.fbx"), [armature, body])


if __name__ == "__main__":
    main()

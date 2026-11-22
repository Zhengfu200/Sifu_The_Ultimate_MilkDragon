"""Run inside the UE 4.26.2 Python commandlet to build the editable Sifu project."""

import json
import os
from pathlib import Path

import unreal


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "build/model"
ASSETS = "/Game/Characters/MainChar/M/Nailoong"
SKELETON = "/Game/Characters/Skeleton/Base_skeleton"
PHYSICS = "/Game/Characters/MainChar/M/Meshes/PhysicAssets"
BODY_MATERIAL = "/Game/Characters/MainChar/M/Materials"
SHARED_MATERIAL = "/Game/Characters/_Shared/Materials/MainChar"
editor = unreal.EditorAssetLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
materials = unreal.MaterialEditingLibrary


def find_or_create(folder, name, cls, factory):
    path = folder + "/" + name
    value = editor.load_asset(path) if editor.does_asset_exist(path) else tools.create_asset(name, folder, cls, factory)
    if value is None:
        raise RuntimeError("Could not create " + path)
    return value


def import_asset(filename, folder, name, options=None):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(MODELS / filename))
    task.set_editor_property("destination_path", folder)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    if options is not None:
        task.set_editor_property("options", options)
    tools.import_asset_tasks([task])
    if not task.get_editor_property("imported_object_paths"):
        raise RuntimeError("Import returned no objects for " + filename)
    return editor.load_asset(folder + "/" + name)


def import_mesh(filename, folder, name, skeleton=None, create_physics=False, vertex_colors=False):
    options = unreal.FbxImportUI()
    options.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_as_skeletal", True)
    options.set_editor_property("skeleton", skeleton)
    for key in ("import_animations", "import_materials", "import_textures"):
        options.set_editor_property(key, False)
    options.set_editor_property("create_physics_asset", create_physics)
    details = options.get_editor_property("skeletal_mesh_import_data")
    details.set_editor_property("convert_scene", True)
    details.set_editor_property("force_front_x_axis", False)
    details.set_editor_property("update_skeleton_reference_pose", False)
    details.set_editor_property("preserve_smoothing_groups", True)
    details.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    if vertex_colors:
        details.set_editor_property("vertex_color_import_option", unreal.VertexColorImportOption.REPLACE)
    return import_asset(filename, folder, name, options)


def base_skeleton():
    if editor.does_asset_exist(SKELETON):
        return editor.load_asset(SKELETON)
    folder = SKELETON.rsplit("/", 1)[0]
    mesh = import_mesh("Base_skeleton.fbx", folder, "SK_BaseSkeletonRef")
    imported = mesh.get_editor_property("skeleton")
    if not editor.rename_asset(imported.get_path_name().split(".")[0], SKELETON):
        raise RuntimeError("Could not name the editor reference skeleton")
    editor.save_loaded_asset(mesh, False)
    return editor.load_asset(SKELETON)


def build_material(variant=None, color_directory=None):
    master = find_or_create(SHARED_MATERIAL, "M_CharaMaster_Cloth_Dyn", unreal.Material, unreal.MaterialFactoryNew())
    master.set_editor_property("used_with_skeletal_mesh", True)
    if variant == "Tongji_Cape" and os.environ.get("SIFU_BUILD_TONGJI_CLOTH") == "1":
        master.set_editor_property("used_with_clothing", True)
    default = unreal.load_asset("/Engine/EngineResources/DefaultTexture")
    normal = unreal.load_asset("/Engine/EngineMaterials/DefaultNormal")
    materials.delete_all_material_expressions(master)
    for index, (name, texture, sampler, output, field) in enumerate((
        ("BaseColor", default, unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, "RGB", unreal.MaterialProperty.MP_BASE_COLOR),
        ("ComboMap", default, unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, "R", unreal.MaterialProperty.MP_ROUGHNESS),
        ("Normal", normal, unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, "RGB", unreal.MaterialProperty.MP_NORMAL),
    )):
        node = materials.create_material_expression(master, unreal.MaterialExpressionTextureSampleParameter2D, -450, index * 250)
        node.set_editor_property("parameter_name", name)
        node.set_editor_property("texture", texture)
        node.set_editor_property("sampler_type", sampler)
        materials.connect_material_property(node, output, field)
    materials.recompile_material(master)
    editor.save_loaded_asset(master, False)

    factory = unreal.MaterialInstanceConstantFactoryNew()
    parent = find_or_create(BODY_MATERIAL, "MI_MainChar_M_BasicOutfit", unreal.MaterialInstanceConstant, factory)
    materials.set_material_instance_parent(parent, master)
    editor.save_loaded_asset(parent, False)
    name = "MI_Nailoong" + ("_" + variant if variant else "")
    instance = find_or_create(ASSETS, name, unreal.MaterialInstanceConstant, factory)
    materials.set_material_instance_parent(instance, parent)
    for parameter, suffix, compression, srgb in (
        ("BaseColor", "BaseColor", unreal.TextureCompressionSettings.TC_DEFAULT, True),
        ("ComboMap", "Combo", unreal.TextureCompressionSettings.TC_MASKS, False),
        ("Normal", "Normal", unreal.TextureCompressionSettings.TC_NORMALMAP, False),
    ):
        name = "T_Nailoong_" + suffix
        if variant and suffix == "BaseColor":
            name = "T_Nailoong_" + variant + "_BaseColor"
            directory = color_directory or ROOT / "build" / variant.lower()
            texture = import_asset(directory / (name + ".png"), ASSETS, name)
        elif variant:
            texture = editor.load_asset(ASSETS + "/" + name)
        else:
            texture = import_asset(name + ".png", ASSETS, name)
        if texture is None:
            raise RuntimeError("Missing texture " + name)
        texture.set_editor_property("compression_settings", compression)
        texture.set_editor_property("srgb", srgb)
        materials.set_material_instance_texture_parameter_value(instance, parameter, texture)
        actual = materials.get_material_instance_texture_parameter_value(instance, parameter)
        if actual != texture:
            raise RuntimeError("Could not set texture parameter " + parameter)
        editor.save_loaded_asset(texture, False)
    editor.save_loaded_asset(instance, False)
    return instance


def physics_placeholders(skeleton):
    names = ("PA_M_MainChar", "PA_M_MainChar_ShadowCapsules")
    paths = [PHYSICS + "/" + name for name in names]
    if not editor.does_asset_exist(paths[0]):
        reference = import_mesh("Base_skeleton.fbx", "/Game/LocalReference", "SK_PhysicsRef", skeleton, create_physics=True)
        source = reference.get_editor_property("physics_asset")
        if source is None or not editor.rename_asset(source.get_path_name().split(".")[0], paths[0]):
            raise RuntimeError("Could not generate the editor physics reference")
        editor.save_loaded_asset(reference, False)
    if not editor.does_asset_exist(paths[1]) and editor.duplicate_asset(paths[0], paths[1]) is None:
        raise RuntimeError("Could not create the editor shadow physics reference")
    result = [editor.load_asset(path) for path in paths]
    for asset in result:
        editor.save_loaded_asset(asset, False)
    return result


wanderer = os.environ.get("SIFU_BUILD_WANDERER") == "1"
tongji = os.environ.get("SIFU_BUILD_TONGJI") == "1"
sirung = tongji and os.environ.get("SIFU_BUILD_SIRUNG") == "1"
cape = sirung and os.environ.get("SIFU_BUILD_TONGJI_CAPE") == "1"
cloth = cape and os.environ.get("SIFU_BUILD_TONGJI_CLOTH") == "1"
variant = "Tongji" if tongji else "Wanderer" if wanderer else None
output = ROOT / "build"
if variant:
    output /= variant.lower()
if cloth:
    output /= "cloth"
elif cape:
    output /= "cape"
elif sirung:
    output /= "sirung"
skeleton = base_skeleton()
material = build_material("Tongji" if tongji else None)
asset_name = "SK_Nailoong" + ("_" + variant if variant else "")
source = output / (asset_name + ".fbx") if variant else asset_name + ".fbx"
if cloth and editor.does_asset_exist(ASSETS + "/" + asset_name):
    existing_mesh = editor.load_asset(ASSETS + "/" + asset_name)
    unreal.SifuModToolsLibrary.remove_all_clothing(existing_mesh)
mesh = import_mesh(source, ASSETS, asset_name, skeleton, vertex_colors=cloth)
slots = list(mesh.get_editor_property("materials"))
if wanderer:
    assignments = {"M_Nailoong": material, "M_Nailoong_Wanderer": build_material("Wanderer")}
elif sirung:
    assignments = {"M_Nailoong": material,
                   "M_Nailoong_Tongji_Sirung": build_material("Tongji_Sirung", output.parent / "sirung")}
    if cape:
        assignments["M_Nailoong_Tongji_Cape"] = build_material("Tongji_Cape", output)
    if cloth:
        assignments["M_Nailoong_Tongji_ClothProxy"] = assignments["M_Nailoong_Tongji_Cape"]
else:
    if len(slots) != 1:
        raise RuntimeError("Expected exactly one texture atlas material slot")
    slots[0].set_editor_property("material_interface", material)
if wanderer or sirung:
    names = {str(slot.get_editor_property("imported_material_slot_name")) for slot in slots}
    if len(slots) != len(assignments) or names != set(assignments):
        raise RuntimeError("Unexpected FBX slots: " + str(names))
    for slot in slots:
        slot.set_editor_property("material_interface", assignments[str(slot.get_editor_property("imported_material_slot_name"))])
mesh.set_editor_property("materials", slots)
physics, shadow = physics_placeholders(skeleton)
mesh.set_editor_property("physics_asset", physics)
mesh.set_editor_property("shadow_physics_asset", shadow)
report = {"mesh": mesh.get_path_name(), "skeleton": skeleton.get_path_name(), "material": material.get_path_name()}
if cloth:
    lib = unreal.SifuModToolsLibrary
    spec = json.loads((output / "cloth.json").read_text(encoding="utf-8"))
    pa = lib.create_physics_asset(ASSETS, "PA_Nailoong_Tongji_Cloth", mesh)
    colliders = lib.build_physics_asset(pa, mesh, json.dumps(spec["physics"]))
    if colliders.startswith("ERROR"):
        raise RuntimeError(colliders)
    editor.save_loaded_asset(pa, False)
    binding = lib.create_cloth_proxy(mesh, spec["proxy_slot"], spec["render_slot"], "Cloth_Tongji_Cape",
                                     pa, spec["max_distance"], False, json.dumps(spec["config"]), 0.0)
    if not binding.startswith("ok ") or "fixed=0 " in binding or "maxdist=0.00" in binding:
        raise RuntimeError(binding)
    # FBX reimport can carry the old proxy's disabled flag over to a visible section.
    visible_slots = set(assignments) - {spec["proxy_slot"]}
    lib.enable_sections(mesh, sorted(visible_slots))
    sections = json.loads(lib.dump_sections(mesh))
    actual_visible = {section["slot"] for section in sections["sections"] if not section["disabled"]}
    if actual_visible != visible_slots:
        raise RuntimeError("Unexpected visible mesh sections: " + json.dumps(sections))
    render, = (section for section in sections["sections"] if section["slot"] == spec["render_slot"])
    proxy, = (section for section in sections["sections"] if section["slot"] == spec["proxy_slot"])
    if render["disabled"] or render["cloth_index"] < 0 or render["mapping"] != render["verts"] or not proxy["disabled"]:
        raise RuntimeError("Clothing mapping is incomplete: " + json.dumps(sections))
    report["cloth"] = {"collision": colliders, "binding": binding, "sections": sections}
editor.save_loaded_asset(mesh, False)
(output / "ue-import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
unreal.log("NAILOONG_IMPORT_COMPLETE")

"""Create original procedural black/gold materials with UE 4.26's editor Python."""
from pathlib import Path
import json
import traceback
import unreal as u

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/execution-domain'
DEST='/Game/ExecutionDomain'
ed=u.EditorAssetLibrary
me=u.MaterialEditingLibrary
tools=u.AssetToolsHelpers.get_asset_tools()

def node(m,cls,**props):
    n=me.create_material_expression(m,cls,0,0)
    for k,v in props.items():n.set_editor_property(k,v)
    return n

def material(name,code,post=False,sphere=False):
    path=DEST+'/'+name
    m=ed.load_asset(path) if ed.does_asset_exist(path) else tools.create_asset(name,DEST,u.Material,u.MaterialFactoryNew())
    me.delete_all_material_expressions(m)
    m.set_editor_property('two_sided',True)
    if post:
        m.set_editor_property('material_domain',u.MaterialDomain.MD_POST_PROCESS)
        m.set_editor_property('blendable_location',u.BlendableLocation.BL_AFTER_TONEMAPPING)
        m.set_editor_property('blendable_priority',100)
    else:
        m.set_editor_property('blend_mode',u.BlendMode.BLEND_ADDITIVE)
        m.set_editor_property('shading_model',u.MaterialShadingModel.MSM_UNLIT)
        m.set_editor_property('disable_depth_test',False)
    uv=node(m,u.MaterialExpressionTextureCoordinate)
    time=node(m,u.MaterialExpressionTime)
    strength=node(m,u.MaterialExpressionScalarParameter,parameter_name='Strength',default_value=0.0 if post else 1.0)
    sources={'UV':(uv,''),'T':(time,''),'Strength':(strength,'')}
    if post:
        scene=node(m,u.MaterialExpressionSceneTexture,scene_texture_id=u.SceneTextureId.PPI_POST_PROCESS_INPUT0)
        sources['Scene']=(scene,'Color')
    if sphere:
        fresnel=node(m,u.MaterialExpressionFresnel,exponent=2.0,base_reflect_fraction=0.03)
        sources['Rim']=(fresnel,'')
    inputs=[]
    for k in sources:
        item=u.CustomInput()
        item.set_editor_property('input_name',k)
        inputs.append(item)
    custom=node(m,u.MaterialExpressionCustom,code=code,output_type=u.CustomMaterialOutputType.CMOT_FLOAT3,inputs=inputs)
    for k,(src,output) in sources.items():
        if not me.connect_material_expressions(src,output,custom,k):raise RuntimeError('Input '+k)
    me.connect_material_property(custom,'',u.MaterialProperty.MP_EMISSIVE_COLOR)
    if not post:
        opacity=node(m,u.MaterialExpressionConstant,r=1.0)
        me.connect_material_property(opacity,'',u.MaterialProperty.MP_OPACITY)
    me.layout_material_expressions(m)
    me.recompile_material(m)
    ed.save_loaded_asset(m,False)
    return m

try:
    ed.make_directory(DEST)
    aura=material('M_GoldAura',r'''
float pulse=0.8+0.2*sin(T*4.5);
float ribbons=0.5+0.5*sin(UV.y*43.0-T*6.5+sin(UV.x*18.0+T)*2.0);
float glow=(pow(Rim,1.8)*(0.20+0.8*ribbons)+0.035)*pulse*Strength;
return float3(3.2,1.35,0.15)*glow;
''',sphere=True)
    material('M_GoldFlame',r'''
float y=saturate(1.0-UV.y);
float wav=sin(y*14.0-T*3.0)*0.10+sin(y*25.0-T*6.0)*0.035;
float x=(UV.x-0.5)+wav*y;
float width=lerp(0.34,0.015,pow(y,0.72));
float body=saturate(1.0-abs(x)/max(width,0.01));
float streak=0.5+0.5*sin(y*22.0-T*8.0+UV.x*9.0);
float shape=pow(body,2.3)*smoothstep(0.0,0.15,y)*pow(1.0-y,0.45);
return lerp(float3(2.0,0.50,0.025),float3(4.0,2.4,0.45),body)*shape*(0.55+0.45*streak)*Strength;
''')
    material('M_GoldRing',r'''
float2 p=(UV-0.5)*2.0;
float r=length(p);
float a=atan2(p.y,p.x);
float ring=exp(-pow((r-0.76)*48.0,2.0));
float inner=exp(-pow((r-0.60)*75.0,2.0))*(0.55+0.45*sin(a*16.0+T));
float rays=pow(saturate(sin(a*24.0+T*0.4)),18.0)*exp(-pow((r-0.69)*14.0,2.0))*0.35;
return float3(3.7,1.65,0.17)*(ring+inner*0.5+rays)*Strength;
''')
    material('M_GoldSpark',r'''
return float3(5.0,2.3,0.24)*Strength*(0.7+0.3*sin(T*8.0+UV.y*13.0));
''')
    material('M_PP_BlackGold',r'''
float3 c=Scene.rgb;
float l=dot(c,float3(0.2126,0.7152,0.0722));
float gold=saturate((c.r-c.b)*4.0)*saturate((c.g-c.b)*5.0);
float3 grade=lerp(l*float3(0.66,0.69,0.74),c*float3(1.02,0.97,0.84),gold*0.80);
float2 q=UV*2.0-1.0;
float vignette=1.0-0.25*saturate(dot(q,q)*0.60);
grade=pow(max(grade,0.0),1.04)*vignette;
return lerp(c,grade,saturate(Strength));
''',post=True)
    for name,source,mat in [('SM_EnergySphere','/Engine/BasicShapes/Sphere',aura),
                            ('SM_EnergyPlane','/Engine/BasicShapes/Plane',ed.load_asset(DEST+'/M_GoldFlame'))]:
        path=DEST+'/'+name
        mesh=ed.load_asset(path) if ed.does_asset_exist(path) else ed.duplicate_asset(source,path)
        mesh.set_material(0,mat)
        ed.save_loaded_asset(mesh,False)
    (OUT/'effects-build.json').write_text(json.dumps({'ok':True,'path':DEST}))
except Exception:
    (OUT/'effects-build.json').write_text(json.dumps({'ok':False,'error':traceback.format_exc()}))
    raise

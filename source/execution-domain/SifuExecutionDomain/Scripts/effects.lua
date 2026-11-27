local UEHelpers=require("UEHelpers")
local folder=debug.getinfo(1,"S").source:sub(2):match("^(.*[/\\])")
local statics=UEHelpers.GetGameplayStatics()
local Effects={}
local GLOW_ENABLED=true
local active={}
local assets={}
local function valid(o)return o~=nil and type(o.IsValid)=="function" and o:IsValid()end
local function same(a,b)return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()end
local function log(s)print("[SifuExecutionDomain:FX] "..s.."\n")end
local function load(name)
    if valid(assets[name])then return assets[name]end
    local path="/Game/ExecutionDomain/"..name.."."..name
    local obj=StaticFindObject(path)
    if not valid(obj)then
        local kismet=StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
        local soft=kismet:MakeSoftObjectPath(path)
        obj=kismet:LoadAsset_Blocking(kismet:Conv_SoftObjPathToSoftObjRef(soft))
    end
    if not valid(obj)then error("Missing effects asset "..name.."; install the companion pak")end
    assets[name]=obj;return obj
end
local function scale(actor,x,y,z)actor:SetActorScale3D({X=x,Y=y,Z=z})end
local function pose(actor,p,r)
    actor:K2_SetActorLocationAndRotation(p,r or {Pitch=0,Yaw=0,Roll=0},false,{},true)
end
local function spawn(s,meshName,materialName,x,y,z)
    local class=StaticFindObject("/Script/Engine.StaticMeshActor")
    local actor=s.world:SpawnActor(class,s.pawn:K2_GetActorLocation(),{Pitch=0,Yaw=0,Roll=0})
    if not valid(actor)then error("Could not create energy actor")end
    table.insert(s.actors,actor)
    actor:SetActorEnableCollision(false)
    actor:SetMobility(2)
    local mesh=actor.StaticMeshComponent
    mesh:SetCollisionEnabled(0)
    mesh:SetCastShadow(false)
    mesh:SetStaticMesh(load(meshName))
    local mid=mesh:CreateDynamicMaterialInstance(0,load(materialName),FName("None"))
    if not valid(mid)then error("Could not create energy material")end
    scale(actor,x,y,z)
    return {actor=actor,mid=mid}
end
local function strength(item,value)
    if valid(item.mid)then item.mid:SetScalarParameterValue(FName("Strength"),value)end
end
local function socket(s,name)
    return s.pawn.Mesh:GetSocketLocation(FName(name))
end
local function grade(s,amount)
    if not valid(s.camera)then return end
    local settings=s.camera.PostProcessSettings
    for name,entry in pairs(s.grade)do
        if type(entry.before)=="table"then
            local value=settings[name]
            for _,key in ipairs({"X","Y","Z","W"})do value[key]=entry.before[key]+(entry.target[key]-entry.before[key])*amount end
        else settings[name]=entry.before+(entry.target-entry.before)*amount end
        settings["bOverride_"..name]=amount>0 or entry.override
    end
end
local function destroy(s)
    if s.grade then grade(s,0)end
    for _,a in ipairs(s.actors)do if valid(a)then a:K2_DestroyActor()end end
    s.actors={};s.dead=true
end
function Effects.start(pawn,world)
    -- Finish the previous fade before re-enabling to avoid accumulating visual actors.
    for _,old in ipairs(active)do destroy(old)end
    active={}
    local s={pawn=pawn,world=world,camera=pawn.CameraComponentThird1,actors={},hands={},flames={},sparks={},trails={},
        started=statics:GetRealTimeSeconds(world),lastTrail=0,trailIndex=0,previousTaking=false,burstAt=-10}
    table.insert(active,s) -- Own partially built effects too, so failures always clean up.
    local ok,err=xpcall(function()
        s.grade={}
        local settings=s.camera.PostProcessSettings
        for name,target in pairs({ColorSaturation={X=0.16,Y=0.16,Z=0.16,W=1},
            ColorContrast={X=1.09,Y=1.09,Z=1.09,W=1},ColorGain={X=0.85,Y=0.88,Z=0.93,W=1},VignetteIntensity=0.43})do
            local value=settings[name]
            if type(target)=="table"then value={X=value.X,Y=value.Y,Z=value.Z,W=value.W}end
            s.grade[name]={before=value,target=target,override=settings["bOverride_"..name]}
        end
        if not GLOW_ENABLED then log("Native grading only (diagnostic)");return end
        for _,bone in ipairs({"hand_l","hand_r"})do
            local item=spawn(s,"SM_EnergySphere","M_GoldAura",0.29,0.29,0.29);item.bone=bone
            table.insert(s.hands,item)
        end
        s.body=spawn(s,"SM_EnergySphere","M_GoldAura",0.85,0.72,1.3)
        for i=1,5 do table.insert(s.flames,spawn(s,"SM_EnergyPlane","M_GoldFlame",0.45,1.1+i*0.06,1))end
        s.ring=spawn(s,"SM_EnergyPlane","M_GoldRing",1,1,1)
        for i=1,10 do
            local item=spawn(s,"SM_EnergySphere","M_GoldSpark",0.015,0.015,0.045)
            item.phase=i*2.39996;table.insert(s.sparks,item)
        end
        for i=1,5 do
            local item=spawn(s,"SM_EnergySphere","M_GoldAura",0.27,0.27,0.40)
            strength(item,0);table.insert(s.trails,item)
        end
        log("Black/gold filter, aura, flames, sparks and trails ready")
    end,debug.traceback)
    if not ok then destroy(s);error(err)end
    return s
end
function Effects.stop(s,immediate)
    if not s or s.dead then return end
    if immediate or not valid(s.world)then destroy(s)
    else s.stopped=statics:GetRealTimeSeconds(s.world)end
end
local function render(s,taking)
    if s.dead then return end
    if not valid(s.world)or not valid(s.pawn)or not same(s.pawn:GetWorld(),s.world)or not valid(s.pawn.Mesh)then destroy(s);return end
    if statics:IsGamePaused(s.world)then return end
    local now=statics:GetRealTimeSeconds(s.world)
    local age=now-s.started
    local amount=math.min(1,age/0.3)
    if s.stopped then amount=math.min(amount,math.max(0,1-(now-s.stopped)/0.4))end
    if amount<=0 and s.stopped then destroy(s);return end
    grade(s,amount)
    if not s.body then return end
    local body=socket(s,"spine_03")
    pose(s.body.actor,body);strength(s.body,0.38*amount)
    local pulse=taking and 1.8 or 1
    for _,item in ipairs(s.hands)do pose(item.actor,socket(s,item.bone));strength(item,amount*pulse)end
    local cameraPos=s.camera:K2_GetComponentLocation()
    local dx,dy=cameraPos.X-body.X,cameraPos.Y-body.Y
    local yaw=math.deg(math.atan(dy,dx))
    for i,item in ipairs(s.flames)do
        local angle=now*0.5+i*math.pi*2/5
        local p={X=body.X+math.cos(angle)*28,Y=body.Y+math.sin(angle)*28,Z=body.Z+18+math.sin(now*1.8+i)*7}
        pose(item.actor,p,{Pitch=0,Yaw=yaw+90,Roll=90});strength(item,amount*0.55)
    end
    for i,item in ipairs(s.sparks)do
        local rise=(age*0.36+i/10)%1
        local angle=item.phase+age*0.32
        pose(item.actor,{X=body.X+math.cos(angle)*(30+rise*12),Y=body.Y+math.sin(angle)*(30+rise*12),Z=body.Z-48+rise*145})
        strength(item,amount*math.sin(rise*math.pi)*0.7)
    end
    if s.previousTaking and not taking then s.burstAt=now end
    s.previousTaking=taking
    local burst=now-s.burstAt
    local wave=age<0.8 and age/0.8 or (burst<0.5 and burst/0.5 or nil)
    if wave then
        local location=s.pawn:K2_GetActorLocation()
        pose(s.ring.actor,{X=location.X,Y=location.Y,Z=location.Z-85})
        local size=0.5+wave*8;scale(s.ring.actor,size,size,1)
        strength(s.ring,amount*(1-wave)*0.65)
    else strength(s.ring,0)end
    if not s.stopped and now-s.lastTrail>0.07 then
        s.lastTrail=now;s.trailIndex=s.trailIndex%#s.trails+1
        local item=s.trails[s.trailIndex]
        pose(item.actor,socket(s,"hand_r"));item.time=now
    end
    for _,item in ipairs(s.trails)do
        strength(item,item.time and amount*math.max(0,1-(now-item.time)/0.30)*0.4 or 0)
    end
end
function Effects.update(s,taking)if s then render(s,taking)end end
function Effects.tick()
    for i=#active,1,-1 do
        local s=active[i]
        if s.stopped then render(s,false)end
        if s.dead then table.remove(active,i)end
    end
end
return Effects

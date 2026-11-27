local statics = require("UEHelpers").GetGameplayStatics()
local effects = {}
local templates = {}
local reported = {}
local foot = FName("foot_l")

local paths = {
    charge = "/Game/Effects/Particles/_Gameplay/P_Absorb_01",
    sparks = "/Game/Effects/Particles/_Gameplay/P_Parry_01",
    strike = "/Game/Effects/Wuguan/ParticleSystems/P_Hit_Push",
    dust = "/Game/Effects/Wuguan/ParticleSystems/Cinemtatics/Hideout_2/P1toP2/P_DustSweep_Feet",
    flash = "/Game/Effects/Wuguan/ParticleSystems/Combat/P_HitHeavy_IGN",
    wave = "/Game/Effects/Wuguan/ParticleSystems/Hideout04/P_ShockWaveImpact_Cine",
}

local function valid(object)
    return object ~= nil and object:IsValid()
end

local function template(name)
    if valid(templates[name]) then return templates[name] end
    local package = paths[name]
    local path = package .. "." .. package:match("[^/]+$")
    local object = StaticFindObject(path)
    if not valid(object) then
        local kismet = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
        object = kismet:LoadAsset_Blocking(kismet:Conv_SoftObjPathToSoftObjRef(kismet:MakeSoftObjectPath(path)))
    end
    if not valid(object) then error("Missing push kick particle " .. path) end
    templates[name] = object
    return object
end

local function size(scale)
    return { X = scale, Y = scale, Z = scale }
end

local function burst(context, name, position, rotation, scale)
    -- Each stock effect is a one-shot. Let the game destroy it when finished.
    -- The final false is Sifu's extra bReplicates parameter.
    local ok, result = pcall(function()
        return statics:SpawnEmitterAtLocation(context, template(name), position, rotation, size(scale), true, 0, true, false)
    end)
    if ok and valid(result) then return true end
    if not reported[name] then
        reported[name] = true
        local detail = ok and "no particle component returned" or tostring(result)
        print("[SifuYangMoves] Push kick " .. name .. " effect: " .. detail .. "\n")
    end
    return false
end

function effects.start(pawn)
    local point = pawn:K2_GetActorLocation()
    local rotation = pawn:K2_GetActorRotation()
    local center = { X = point.X, Y = point.Y, Z = point.Z + 22 }
    return burst(pawn, "charge", center, rotation, 1.45)
end

function effects.release(pawn)
    local point = pawn:K2_GetActorLocation()
    local rotation = pawn:K2_GetActorRotation()
    local ground = { X = point.X, Y = point.Y, Z = point.Z - pawn.CapsuleComponent:GetScaledCapsuleHalfHeight() + 4 }
    local yaw = math.rad(rotation.Yaw)
    local reach = { X = point.X + 75 * math.cos(yaw), Y = point.Y + 75 * math.sin(yaw), Z = point.Z + 18 }
    local mesh = pawn.Mesh
    local footPoint = valid(mesh) and mesh:GetSocketLocation(foot) or reach
    burst(pawn, "dust", ground, rotation, 1.40)
    burst(pawn, "sparks", { X = footPoint.X, Y = footPoint.Y, Z = math.max(footPoint.Z, ground.Z + 42) }, rotation, 1.45)
    local visible = burst(pawn, "strike", reach, rotation, 1.70)
    if visible then print("[SifuYangMoves] Push kick release effects spawned\n") end
end

function effects.impact(world, pawn, position, floor, rotation)
    if not valid(pawn) or not valid(world) then return end
    local currentWorld = pawn:GetWorld()
    if not valid(currentWorld) or currentWorld:GetAddress() ~= world:GetAddress() then return end
    local flash = burst(pawn, "flash", position, rotation, 2.05)
    local wave = burst(pawn, "wave", floor, rotation, 1.25)
    if flash or wave then print("[SifuYangMoves] Push kick impact effects spawned\n") end
end

return effects

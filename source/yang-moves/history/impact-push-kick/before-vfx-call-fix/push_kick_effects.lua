local statics = require("UEHelpers").GetGameplayStatics()
local effects = {}
local templates = {}
local zero = { X = 0, Y = 0, Z = 0 }
local flat = { Pitch = 0, Yaw = 0, Roll = 0 }
local foot = FName("foot_l")

local paths = {
    charge = "/Game/Effects/Particles/_Gameplay/P_Absorb_TrianglesLight_01",
    streak = "/Game/Effects/Wuguan/_Temp/ShockWaveH4/FengjieAttacks/Fendjie_trail/P_HammerHead_Trail_Quick_Unparryable",
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
    local component = statics:SpawnEmitterAtLocation(context, template(name), position, rotation, size(scale), true, 0, true)
    if not valid(component) then error("Could not spawn push kick " .. name) end
end

local function attach(mesh, name, scale)
    local component = statics:SpawnEmitterAttached(template(name), mesh, foot, zero, flat, size(scale), 0, true, 0, true)
    if not valid(component) then error("Could not attach push kick " .. name) end
    return component
end

function effects.start(pawn)
    return attach(pawn.Mesh, "charge", 1.35)
end

function effects.release(pawn)
    local point = pawn:K2_GetActorLocation()
    local ground = { X = point.X, Y = point.Y, Z = point.Z - pawn.CapsuleComponent:GetScaledCapsuleHalfHeight() + 4 }
    burst(pawn, "dust", ground, pawn:K2_GetActorRotation(), 1.15)
    return attach(pawn.Mesh, "streak", 1.25)
end

function effects.stop(emitter)
    if valid(emitter) then emitter:DeactivateSystem() end
end

function effects.impact(world, pawn, position, floor, rotation)
    if not valid(pawn) or not valid(world) then return end
    local currentWorld = pawn:GetWorld()
    if not valid(currentWorld) or currentWorld:GetAddress() ~= world:GetAddress() then return end
    burst(pawn, "flash", position, rotation, 1.65)
    burst(pawn, "wave", floor, rotation, 1.0)
    print("[SifuYangMoves] Push kick impact effects spawned\n")
end

return effects

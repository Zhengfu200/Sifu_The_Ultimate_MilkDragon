local UEHelpers = require("UEHelpers")

-- Set this to an integer from 1 to 5 to cap the volley.
local MAX_TARGETS = 5
local DIZZY_MILLISECONDS = 1800
local FLIGHT_SPEED = 2200
local BOTTLE_PATH = "/Game/Blueprints/LDIngredients/Weapons/MakeShift_OneHandedFamily/Bottle/BP_Throwable_Bottle.BP_Throwable_Bottle"

local function log(message)
    print("[SifuThrowStun] " .. message .. "\n")
end

if not EngineTickAvailable then
    log("EngineTick unavailable")
    return
end

local folder = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local library = folder .. "DizzyBridge.dll"
local applyDizzy, bridgeError = package.loadlib(library, "ApplyDizzy")
local isEnemy = package.loadlib(library, "IsEnemy")
if not applyDizzy or not isEnemy or applyDizzy(0, 0, 0) ~= 1 then
    log("Unsupported game or UE4SS build: " .. tostring(bridgeError or "native functions unavailable"))
    return
end

local bottleClass
local session

local function valid(object)
    return object ~= nil and type(object.IsValid) == "function" and object:IsValid()
end

local function same(a, b)
    return valid(a) and valid(b) and a:GetAddress() == b:GetAddress()
end

local function localPlayer()
    for _, controller in ipairs(FindAllOf("PlayerController") or {}) do
        if valid(controller) then
            local player, pawn = controller.Player, controller.Pawn
            if valid(player) and player:GetClass():GetFName():ToString():find("LocalPlayer", 1, true)
                and valid(pawn) and pawn:GetClass():GetFName():ToString() == "BP_FightingPlayer_C" then
                local world = pawn:GetWorld()
                if valid(world) then return controller, pawn, world end
            end
        end
    end
end

local function canPlay(controller, pawn, world, statics)
    return valid(controller) and valid(pawn) and valid(world) and not controller.bShowMouseCursor
        and not statics:IsGamePaused(world) and not pawn:IsDead() and not pawn:BPF_IsDown()
        and not pawn:BPF_IsInCinematic() and valid(pawn.CameraComponentThird1)
        and not pawn.CameraComponentThird1:BPF_IsInCinematic()
end

local function vector(x, y, z)
    return { X = x, Y = y, Z = z }
end

local function offsetZ(position, height)
    return vector(position.X, position.Y, position.Z + height)
end

local function distanceSquared(a, b)
    local x, y, z = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return x * x + y * y + z * z
end

local function canTarget(actor, state)
    if not valid(actor) or same(actor, state.pawn) then return false, "self/invalid" end
    if actor.bHidden == true then return false, "hidden" end
    if not same(actor:GetWorld(), state.world) then return false, "other world" end
    if not valid(actor.Controller) then return false, "no controller" end
    if actor:IsDead() or actor:BPF_IsDown() then return false, "dead/down" end
    if actor:BPF_IsInCinematic() then return false, "cinematic" end
    local result = isEnemy(actor:GetAddress(), state.pawn:GetAddress(), state.game:GetAddress())
    return result == 1, "native " .. tostring(result)
end

local function findTargets(state, origin, playerLocation)
    local candidates = {}
    local actors = FindObjects(0, "FightingCharacter", nil, EObjectFlags.RF_NoFlags,
        EObjectFlags.RF_ClassDefaultObject | EObjectFlags.RF_ArchetypeObject, false) or {}
    local counts = {}
    for _, actor in pairs(actors) do
        local eligible, reason = canTarget(actor, state)
        if eligible and state.controller:LineOfSightTo(actor, origin, false) then
            candidates[#candidates + 1] = {
                actor = actor,
                distance = distanceSquared(playerLocation, actor:K2_GetActorLocation()),
                address = actor:GetAddress(),
            }
        else
            reason = eligible and "occluded" or reason
            counts[reason] = (counts[reason] or 0) + 1
        end
    end
    if #candidates == 0 then
        local details = {}
        for reason, count in pairs(counts) do details[#details + 1] = reason .. "=" .. count end
        log("Selection scanned " .. #actors .. " fighting characters (" .. table.concat(details, ", ") .. ")")
    end
    table.sort(candidates, function(a, b)
        if a.distance == b.distance then return a.address < b.address end
        return a.distance < b.distance
    end)
    return candidates
end

local function loadBottleClass()
    if valid(bottleClass) then return bottleClass end
    bottleClass = StaticFindObject(BOTTLE_PATH .. "_C")
    if valid(bottleClass) then return bottleClass end
    local libraryObject = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
    local softPath = libraryObject:MakeSoftClassPath(BOTTLE_PATH .. "_C")
    bottleClass = libraryObject:LoadClassAsset_Blocking(libraryObject:Conv_SoftClassPathToSoftClassRef(softPath))
    return bottleClass
end

local function destroyBottle(shot)
    if valid(shot.bottle) then shot.bottle:K2_DestroyActor() end
end

local function finish()
    local current = session
    session = nil
    if not current then return end
    for _, shot in ipairs(current.shots) do pcall(destroyBottle, shot) end
end

local function spawnBottle(state, candidate, origin, delay)
    local target = candidate.actor
    local destination = offsetZ(target:K2_GetActorLocation(), 45)
    local bottle = state.world:SpawnActor(state.bottleClass, origin, { Pitch = 0, Yaw = 0, Roll = 0 })
    if not valid(bottle) then return end
    local shot = {
        bottle = bottle,
        target = target,
        origin = origin,
        delay = delay,
        travel = math.max(0.16, math.min(0.85, math.sqrt(distanceSquared(origin, destination)) / FLIGHT_SPEED)),
        hitResult = {},
    }
    state.shots[#state.shots + 1] = shot
    bottle:SetActorEnableCollision(false)
    bottle:SetActorTickEnabled(false)
    local root = bottle.RootComponent
    if valid(root) and root:IsA(StaticFindObject("/Script/Engine.PrimitiveComponent")) then
        root:SetSimulatePhysics(false)
    end
    bottle:SetActorHiddenInGame(delay > 0)
    return shot
end

local function throwVolley()
    if session then return end
    local controller, pawn, world = localPlayer()
    local statics = UEHelpers.GetGameplayStatics()
    if not canPlay(controller, pawn, world, statics) then return end
    local game = statics:GetGameInstance(world)
    if not valid(game) or not game:IsA(StaticFindObject("/Script/Sifu.ThePlainesGameInstance")) then return end

    local state = {
        controller = controller, pawn = pawn, world = world, statics = statics, game = game, shots = {},
    }
    local playerLocation = pawn:K2_GetActorLocation()
    local origin = offsetZ(playerLocation, 58)
    local candidates = findTargets(state, origin, playerLocation)
    if #candidates == 0 then
        log("No valid enemy in sight")
        return
    end

    state.bottleClass = loadBottleClass()
    if not valid(state.bottleClass) then
        log("Could not load the original bottle class")
        return
    end
    state.started = statics:GetTimeSeconds(world)
    session = state
    for index = 1, math.min(MAX_TARGETS, #candidates) do
        spawnBottle(state, candidates[index], origin, (index - 1) * 0.035)
    end
    log(string.format("Launched %d bottle(s), %d eligible", #state.shots, #candidates))
    if #state.shots == 0 then finish() end
end

local function advanceShot(shot, state, elapsed)
    if not valid(shot.bottle) or not canTarget(shot.target, state) then return true end
    if elapsed < shot.delay then return false end

    if not shot.visible then
        shot.visible = true
        shot.bottle:SetActorHiddenInGame(false)
    end
    local progress = math.min(1, (elapsed - shot.delay) / shot.travel)
    local start = shot.origin
    local destination = offsetZ(shot.target:K2_GetActorLocation(), 45)
    local arc = 4 * 30 * progress * (1 - progress)
    local position = vector(
        start.X + (destination.X - start.X) * progress,
        start.Y + (destination.Y - start.Y) * progress,
        start.Z + (destination.Z - start.Z) * progress + arc
    )
    shot.bottle:K2_SetActorLocationAndRotation(
        position, { Pitch = 720 * progress, Yaw = 0, Roll = 0 }, false, shot.hitResult, true)
    if progress < 1 then return false end
    if not state.controller:LineOfSightTo(shot.target, start, false) then return true end

    local result = applyDizzy(shot.target:GetAddress(), state.pawn:GetAddress(), DIZZY_MILLISECONDS)
    if result == -2 then
        shot.target:BPF_LaunchImpact(0, false, DIZZY_MILLISECONDS / 1000)
    end
    log(string.format("Hit %s (%s)", shot.target:GetFName():ToString(),
        ({ [1] = "dizzy", [2] = "already dizzy", [-2] = "stagger" })[result] or "rejected"))
    return true
end

local function update()
    local state = session
    if not state then return end
    if not valid(state.pawn) or not valid(state.world) or not valid(state.controller)
        or not same(state.controller.Pawn, state.pawn) or not canPlay(state.controller, state.pawn, state.world, state.statics) then
        finish()
        return
    end
    local elapsed = state.statics:GetTimeSeconds(state.world) - state.started
    for index = #state.shots, 1, -1 do
        local shot = state.shots[index]
        if advanceShot(shot, state, elapsed) then
            destroyBottle(shot)
            table.remove(state.shots, index)
        end
    end
    if #state.shots == 0 then finish() end
end

local function guarded(callback)
    local ok, err = xpcall(callback, debug.traceback)
    if not ok then
        finish()
        log(tostring(err))
    end
end

RegisterKeyBind(Key.V, function()
    ExecuteInGameThread(function() guarded(throwVolley) end, EGameThreadMethod.EngineTick)
end)
LoopInGameThreadAfterFrames(1, function()
    if session then guarded(update) end
end)

log("Ready. Press V during gameplay.")

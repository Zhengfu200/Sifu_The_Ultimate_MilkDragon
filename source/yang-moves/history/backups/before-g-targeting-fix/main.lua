local UEHelpers = require("UEHelpers")

local moves = {
    { key = Key.Z, name = "YangPushKick", attack = "Yang_SidePushKick_FL" },
    { key = Key.X, name = "YangRushSweep", attack = "Yang_Rush_Sweep_FL" },
    { key = Key.C, name = "YangTripleHit", attack = "Yang_TripleHit_FL" },
    { key = Key.G, name = "YangMultiHit", attack = "YangUnblockableMultiHit", rounds = 1, speed = 1.5, blink = true },
}

local function log(message)
    print("[SifuYangMoves] " .. message .. "\n")
end

if not EngineTickAvailable then
    log("EngineTick unavailable")
    return
end

local script = debug.getinfo(1, "S").source
local folder = script:sub(2):match("^(.*[/\\])")
local queueLightAttack, bridgeError = package.loadlib(folder .. "YangInputBridge.dll", "QueueLightAttack")
if not queueLightAttack then
    log("input bridge unavailable: " .. tostring(bridgeError))
    return
end

local pending

local function valid(object)
    return object ~= nil and object:IsValid()
end

local function same(a, b)
    return valid(a) and valid(b) and a:GetAddress() == b:GetAddress()
end

local function localPlayer()
    for _, controller in ipairs(FindAllOf("PlayerController") or {}) do
        local player, pawn = controller.Player, controller.Pawn
        if valid(player) and player:GetClass():GetFName():ToString():find("LocalPlayer", 1, true) and
            valid(pawn) and pawn:GetClass():GetFName():ToString() == "BP_FightingPlayer_C" then
            local level = pawn:GetOuter()
            local world = valid(level) and level:GetOuter() or nil
            if valid(world) then return controller, pawn, world end
        end
    end
end

local function canAttack(controller, pawn, world)
    return not controller.bShowMouseCursor and not UEHelpers.GetGameplayStatics():IsGamePaused(world)
        and not pawn:IsDead() and not pawn:BPF_IsDown() and not pawn:BPF_IsInCinematic()
        and valid(pawn.CameraComponentThird1) and not pawn.CameraComponentThird1:BPF_IsInCinematic()
        and not valid(pawn:BPF_GetPickedUpWeapon())
end

-- All distances are Unreal units (centimeters). Lock one target for the cast.
local FRONT_DISTANCE = 105
local FOLLOW_TOLERANCE = 18

local function nearestEnemy(pawn, world)
    local origin = pawn:K2_GetActorLocation()
    local componentClass = StaticFindObject("/Script/Sifu.AIFightingComponent")
    local nearest, nearestDistance
    for _, ai in ipairs(FindAllOf("FightingAIController") or {}) do
        local target = ai.Pawn
        if valid(target) and not same(target, pawn) and same(ai:GetWorld(), world)
            and not target.bHidden and not target:IsDead() and not target:IsActorBeingDestroyed() then
            local fighting = target:GetComponentByClass(componentClass)
            local enemy = valid(fighting) and fighting:BPF_GetEnemy() or nil
            if not valid(enemy) or same(enemy, pawn) then
                local location = target:K2_GetActorLocation()
                local dx, dy, dz = location.X - origin.X, location.Y - origin.Y, location.Z - origin.Z
                local distance = dx * dx + dy * dy + dz * dz
                if not nearestDistance or distance < nearestDistance then
                    nearest, nearestDistance = target, distance
                end
            end
        end
    end
    return nearest
end

local function targetAvailable(session)
    local target = session.target
    return valid(target) and same(target:GetWorld(), session.world)
        and not target:IsDead() and not target:IsActorBeingDestroyed()
end

local function followTarget(session, initial)
    if not targetAvailable(session) then return false end
    local pawn, target = session.pawn, session.target
    local position = target:K2_GetActorLocation()
    local destination = {
        X = position.X + session.frontX * FRONT_DISTANCE,
        Y = position.Y + session.frontY * FRONT_DISTANCE,
        Z = position.Z,
    }
    local rotation = {
        Pitch = 0,
        Yaw = math.deg(math.atan(-session.frontY, -session.frontX)),
        Roll = 0,
    }
    local here = pawn:K2_GetActorLocation()
    local dx, dy, dz = here.X - destination.X, here.Y - destination.Y, here.Z - destination.Z
    if initial or dx * dx + dy * dy + dz * dz > FOLLOW_TOLERANCE * FOLLOW_TOLERANCE then
        -- TeleportTo tests the character capsule and adjusts the destination for collision.
        if not pawn:K2_TeleportTo(destination, rotation) then
            return false
        end
    end
    pawn:K2_SetActorRotation(rotation, true)
    return true
end

local function restore(session, reason)
    if pending ~= session then return end
    pending = nil
    -- Restore only values still owned by this session.
    if session.pawnApplied and valid(session.pawn)
        and math.abs(session.pawn.CustomTimeDilation - session.pawnApplied) < 0.0001 then
        session.pawn.CustomTimeDilation = session.pawnBefore
    end
    if session.meshApplied and valid(session.mesh)
        and math.abs(session.mesh.GlobalAnimRateScale - session.meshApplied) < 0.0001 then
        session.mesh.GlobalAnimRateScale = session.meshBefore
    end
    if valid(session.component) then
        session.component:BPF_ResetToDefaultCombo()
    end
    log(reason)
end

local function loadCombo(move)
    local path = "/Game/YangMoves/" .. move.name .. "." .. move.name
    local combo = StaticFindObject(path)
    if not valid(combo) then
        local library = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
        local reference = library:Conv_SoftObjPathToSoftObjRef(library:MakeSoftObjectPath(path))
        combo = library:LoadAsset_Blocking(reference)
    end
    if not valid(combo) then error("Cannot load " .. path) end
    return combo
end

local function realTime(world)
    return UEHelpers.GetGameplayStatics():GetRealTimeSeconds(world)
end

local function beginAttack(session)
    local move = session.move
    session.started = false
    session.maxRatio = 0
    session.deadline = realTime(session.world) + 1.0
    session.retryFrame = 0
    session.component:BPF_ResetToDefaultCombo()
    session.component:BPF_OverrideCombo(loadCombo(move))
    queueLightAttack()
end

local function watch(session)
    local controller, pawn, world = localPlayer()
    if not same(pawn, session.pawn) or not same(world, session.world)
        or not canAttack(controller, pawn, world) or not valid(session.component) then
        restore(session, "Cancelled (player state changed)")
        return
    end

    if session.target and not followTarget(session, false) then
        restore(session, "Cancelled (target gone or approach blocked)")
        return
    end
    local playing = session.component:BPF_IsPlayingAttack()
    if playing then
        local name = session.component:BPF_GetCurrentAttackName():ToString()
        if not name:find("." .. session.move.attack, 1, true) then
            restore(session, "Cancelled (another attack started)")
            return
        end
        session.maxRatio = math.max(session.maxRatio, session.component:BPF_GetCurrentAttackRatio())
        if not session.started then
            session.started = true
            log(string.format("Started %s [%d/%d] speed=%.2f", session.move.name, session.round, session.rounds, session.move.speed or 1))
        end
    elseif session.started then
        log(string.format("Finished %s [%d/%d] ratio=%.3f", session.move.name, session.round, session.rounds, session.maxRatio))
        if session.round == session.rounds then
            restore(session, "Complete")
            return
        end
        if session.maxRatio < 0.80 then
            restore(session, "Cancelled (attack interrupted)")
            return
        end
        session.round = session.round + 1
        beginAttack(session)
    elseif realTime(world) >= session.deadline then
        restore(session, "Cancelled (attack did not start)")
        return
    else
        -- A previous attack can briefly retain its recovery state. Retry only
        -- while no attack is playing and stop after the bounded start window.
        session.retryFrame = session.retryFrame + 1
        if session.retryFrame % 6 == 0 then queueLightAttack() end
    end
end

local function guarded(callback)
    local ok, err = pcall(callback)
    if ok then return end
    if pending then pcall(restore, pending, "Cancelled (script error)") end
    log(tostring(err))
end

local function activate(move)
    if pending then return end
    local controller, pawn, world = localPlayer()
    if not pawn or not canAttack(controller, pawn, world) then return end
    local component = pawn.Attack
    if not valid(component) or component:BPF_IsPlayingAttack() then return end
    local session = {
        move = move, round = 1, rounds = move.rounds or 1,
        pawn = pawn, world = world, component = component,
    }
    if move.blink then
        session.target = nearestEnemy(pawn, world)
        if not valid(session.target) then
            log("No living enemy available")
            return
        end
        local forward = session.target:GetActorForwardVector()
        local length = math.sqrt(forward.X * forward.X + forward.Y * forward.Y)
        if length < 0.0001 then return end
        session.frontX, session.frontY = forward.X / length, forward.Y / length
        -- Preload before moving, so a missing asset cannot leave the player relocated.
        loadCombo(move)
        if not followTarget(session, true) then
            log("Cannot teleport to the enemy front")
            return
        end
        log("Blink target: " .. session.target:GetFullName())
    end
    pending = session
    if move.speed then
        session.mesh = pawn.Mesh
        if not valid(session.mesh) then error("Player mesh unavailable") end
        session.pawnBefore = pawn.CustomTimeDilation
        session.meshBefore = session.mesh.GlobalAnimRateScale
        session.pawnApplied = session.pawnBefore * move.speed
        session.meshApplied = session.meshBefore * move.speed
        pawn.CustomTimeDilation = session.pawnApplied
        -- This game's player mesh uses world delta independently of actor timing.
        session.mesh.GlobalAnimRateScale = session.meshApplied
        log(string.format("Speed applied pawn=%.3f mesh=%.3f", session.pawnApplied, session.meshApplied))
    end
    beginAttack(session)
end

for _, move in ipairs(moves) do
    RegisterKeyBind(move.key, function()
        ExecuteInGameThread(function()
            guarded(function() activate(move) end)
        end, EGameThreadMethod.EngineTick)
    end)
end

LoopInGameThreadAfterFrames(1, function()
    if pending then guarded(function() watch(pending) end) end
end)
log("Ready. Z/X/C: single attacks. G: blink to nearest enemy, five punches at 1.5x speed, no guard/deflect/dodge/avoid.")

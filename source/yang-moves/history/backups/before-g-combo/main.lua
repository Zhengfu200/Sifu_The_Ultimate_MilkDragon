local UEHelpers = require("UEHelpers")

local moves = {
    { key = Key.Z, name = "YangPushKick", attack = "Yang_SidePushKick_FL" },
    { key = Key.X, name = "YangRushSweep", attack = "Yang_Rush_Sweep_FL" },
    { key = Key.C, name = "YangTripleHit", attack = "Yang_TripleHit_FL" },
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

local function restore(session)
    pending = nil
    local component = session.component
    if valid(component) then
        component:BPF_ResetToDefaultCombo()
    end
end

local function watch(session)
    local controller, pawn, world = localPlayer()
    if not same(pawn, session.pawn) or not same(world, session.world)
        or not canAttack(controller, pawn, world) or not valid(session.component) then
        restore(session)
        return
    end

    local playing = session.component:BPF_IsPlayingAttack()
    if playing and not session.started then
        session.started = true
        log("Started " .. session.move.name .. " (" .. session.component:BPF_GetCurrentAttackName():ToString() .. ")")
    elseif not playing and session.started then
        restore(session)
        log("Finished " .. session.move.name)
        return
    elseif not session.started and os.clock() >= session.deadline then
        restore(session)
        log("No native attack started for " .. session.move.name)
        return
    end
    ExecuteInGameThreadAfterFrames(1, function()
        if pending ~= session then return end
        local ok, err = pcall(watch, session)
        if not ok then
            pcall(restore, session)
            log(tostring(err))
        end
    end)
end

local function activate(move)
    if pending then return end
    local controller, pawn, world = localPlayer()
    if not pawn or not canAttack(controller, pawn, world) then return end
    local component = pawn.Attack
    if not valid(component) or component:BPF_IsPlayingAttack() then return end

    local path = "/Game/YangMoves/" .. move.name .. "." .. move.name
    local combo = StaticFindObject(path)
    if not valid(combo) then
        local library = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
        local softPath = library:MakeSoftObjectPath(path)
        local reference = library:Conv_SoftObjPathToSoftObjRef(softPath)
        combo = library:LoadAsset_Blocking(reference)
    end
    if not valid(combo) then
        log("Cannot load " .. path)
        return
    end

    local session = {
        move = move,
        pawn = pawn,
        world = world,
        component = component,
        deadline = os.clock() + 0.65,
    }
    pending = session
    component:BPF_OverrideCombo(combo)
    queueLightAttack()
    watch(session)
end

for _, move in ipairs(moves) do
    RegisterKeyBind(move.key, function()
        ExecuteInGameThread(function()
            local ok, err = pcall(activate, move)
            if not ok then
                if pending then pcall(restore, pending) end
                log(tostring(err))
            end
        end, EGameThreadMethod.EngineTick)
    end)
end
log("Ready. Press Z, X, or C during gameplay.")

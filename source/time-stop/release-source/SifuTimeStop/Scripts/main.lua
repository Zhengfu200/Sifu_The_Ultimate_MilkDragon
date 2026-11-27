local UEHelpers = require("UEHelpers")

local WORLD_SPEED = 0.10
local PLAYER_SPEED = 1.50
local FOCUS_START_EVENT =
    "BndEvt__Attack_K2Node_ComponentBoundEvent_1_OnFocusMechanicStart__DelegateSignature"

local session
local nativeRecovery

local function log(message)
    print("[SifuTimeStop] " .. message .. "\n")
end

if not EngineTickAvailable then
    log("EngineTick is unavailable. Install the bundled UE4SS build.")
    return
end

local function valid(object)
    return object ~= nil and object:IsValid()
end

local function same(a, b)
    return valid(a) and valid(b) and a:GetAddress() == b:GetAddress()
end

local function near(a, b)
    return math.abs(a - b) < 0.0001
end

local function statics()
    return UEHelpers.GetGameplayStatics()
end

local function playerPawn(controller)
    return controller.Pawn
end

local function actorWorld(actor)
    local level = actor:GetOuter()
    if valid(level) then return level:GetOuter() end
end

local function localController()
    for _, controller in ipairs(FindAllOf("PlayerController") or {}) do
        local player = controller.Player
        local pawn = playerPawn(controller)
        if valid(player) and player:GetClass():GetFName():ToString():find("LocalPlayer", 1, true)
            and valid(pawn) and pawn:GetClass():GetFName():ToString() == "BP_FightingPlayer_C" then
            local world = actorWorld(pawn)
            if valid(world) then return controller, world end
        end
    end
end

local function focusWeight(pawn)
    local index = pawn.ID_FocusModeMID
    if index < 0 then return 0 end
    return pawn.CameraComponentThird1.PostProcessSettings.WeightedBlendables.Array[index + 1].Weight
end

local function blocked(pawn, world)
    if statics():IsGamePaused(world) then return "paused" end
    if pawn:IsDead() then return "player is dead" end
    if pawn:BPF_IsInCinematic() or pawn.CameraComponentThird1:BPF_IsInCinematic() then
        return "cinematic"
    end
end

local function restoreTime(state)
    if valid(state.world) and near(statics():GetGlobalTimeDilation(state.world), state.worldApplied) then
        statics():SetGlobalTimeDilation(state.world, state.worldBefore)
    end
    if state.pawnApplied and valid(state.pawn) and near(state.pawn.CustomTimeDilation, state.pawnApplied) then
        state.pawn.CustomTimeDilation = state.pawnBefore
    end
    if state.animApplied and valid(state.mesh) and near(state.mesh.GlobalAnimRateScale, state.animApplied) then
        state.mesh.GlobalAnimRateScale = state.animBefore
    end
end

local function restoreBlur(state)
    if not valid(state.camera) then return end
    local settings = state.camera.PostProcessSettings
    settings.MotionBlurAmount = state.blurAmount
    settings.MotionBlurTargetFPS = state.blurFPS
    settings.bOverride_MotionBlurAmount = state.overrideAmount
    settings.bOverride_MotionBlurTargetFPS = state.overrideFPS
end

local function closeEffect(state)
    if valid(state.pawn) and state.pawn.ID_FocusModeMID >= 0 then
        state.pawn:DisableFocusModePP()
    end
    restoreBlur(state)
end

local function stop(fade, reason)
    local state = session
    if not state then return end
    restoreTime(state)
    if fade and valid(state.pawn) and state.fadeDuration > 0 then
        state.pawn:StartFocusPPFadeOut()
        restoreBlur(state)
        state.fadeUntil = statics():GetTimeSeconds(state.world) + state.fadeDuration
    else
        closeEffect(state)
        session = nil
    end
    log("OFF (" .. reason .. ")")
end

local function start(controller, pawn, world)
    local mesh = pawn.Mesh
    if not valid(mesh) or type(mesh.GlobalAnimRateScale) ~= "number" then
        error("the player animation rate is unavailable")
    end
    local settings = pawn.CameraComponentThird1.PostProcessSettings
    local focusDB = pawn.Attack:BPF_GetFocusDB()
    local worldBefore = statics():GetGlobalTimeDilation(world)
    if worldBefore <= 0 then return end
    local pawnBefore = pawn.CustomTimeDilation
    local state = {
        controller = controller,
        pawn = pawn,
        world = world,
        mesh = mesh,
        camera = pawn.CameraComponentThird1,
        worldBefore = worldBefore,
        pawnBefore = pawnBefore,
        animBefore = mesh.GlobalAnimRateScale,
        worldApplied = worldBefore * WORLD_SPEED,
        blurAmount = settings.MotionBlurAmount,
        blurFPS = settings.MotionBlurTargetFPS,
        overrideAmount = settings.bOverride_MotionBlurAmount,
        overrideFPS = settings.bOverride_MotionBlurTargetFPS,
        fadeDuration = focusDB.m_fPostProcessFadeOutDuration,
    }
    session = state
    statics():SetGlobalTimeDilation(world, state.worldApplied)
    state.worldApplied = statics():GetGlobalTimeDilation(world)
    if state.worldApplied <= 0 then error("invalid world time dilation") end
    -- The player's mesh animation uses world delta independently of actor timing.
    local speedCompensation = worldBefore * PLAYER_SPEED / state.worldApplied
    state.pawnApplied = pawnBefore * speedCompensation
    state.animApplied = state.animBefore * speedCompensation
    pawn.CustomTimeDilation = state.pawnApplied
    mesh.GlobalAnimRateScale = state.animApplied
    pawn["Enable Focus Mode PP"](pawn)
    if focusWeight(pawn) <= 0 then error("the Focus material did not activate") end
    log(string.format(
        "ON (world %.3f, pawn %.3f, combined %.3f, mesh %.3f, fade out %.3fs)",
        state.worldApplied, pawn.CustomTimeDilation, state.worldApplied * pawn.CustomTimeDilation,
        mesh.GlobalAnimRateScale, state.fadeDuration
    ))
end

local function toggle()
    if session and not session.fadeUntil then
        stop(true, "T")
        return
    end
    local controller, world = localController()
    if not valid(controller) then
        log("T ignored (no player controller)")
        return
    end
    local pawn = playerPawn(controller)
    if not valid(pawn) or not valid(pawn.CameraComponentThird1) or not valid(pawn.Attack) then
        log("T ignored (no playable character)")
        return
    end
    local reason = blocked(pawn, world)
    if reason then
        log("T ignored (" .. reason .. ")")
        return
    end
    if session and not same(session.pawn, pawn) then stop(false, "player changed") end
    if not session and focusWeight(pawn) > 0 then return end
    start(controller, pawn, world)
end

local function recoverNativeFocus()
    local state = nativeRecovery
    if not state then return end
    restoreTime(state)
    restoreBlur(state)
    nativeRecovery = nil
end

local function update()
    if nativeRecovery and (not valid(nativeRecovery.pawn) or focusWeight(nativeRecovery.pawn) == 0) then
        recoverNativeFocus()
    end
    local state = session
    if not state then return end
    if not valid(state.controller) or not valid(state.world)
        or not same(playerPawn(state.controller), state.pawn)
        or not same(actorWorld(state.pawn), state.world)
        or not same(state.pawn.Mesh, state.mesh)
        or blocked(state.pawn, state.world) then
        stop(false, "left gameplay")
    elseif state.fadeUntil then
        if statics():GetTimeSeconds(state.world) >= state.fadeUntil then
            closeEffect(state)
            session = nil
        end
    elseif not near(statics():GetGlobalTimeDilation(state.world), state.worldApplied) then
        stop(false, "game changed time scale")
    end
end

local function guarded(callback)
    local ok, err = pcall(callback)
    if ok then return end
    log(tostring(err))
    local state = session
    session = nil
    if state then
        local timeOK, timeErr = pcall(restoreTime, state)
        if not timeOK then log("time restore failed: " .. tostring(timeErr)) end
        local effectOK, effectErr = pcall(closeEffect, state)
        if not effectOK then log("effect restore failed: " .. tostring(effectErr)) end
    end
end

-- This blueprint event runs after the native Focus implementation has taken ownership
-- of the camera. Leave its post-process active and release only the speed we still own.
RegisterCustomEvent(FOCUS_START_EVENT, function(context)
    if not session or not same(session.pawn, context:get()) then return end
    guarded(function()
        nativeRecovery = session
        session = nil
        restoreTime(nativeRecovery)
        log("OFF (handed off to native Focus)")
    end)
end)

RegisterKeyBind(Key.T, function()
    ExecuteInGameThread(function() guarded(toggle) end, EGameThreadMethod.EngineTick)
end)

LoopInGameThreadAfterFrames(1, function()
    if session or nativeRecovery then
        guarded(update)
    end
end)

log("Ready. Press T during gameplay.")

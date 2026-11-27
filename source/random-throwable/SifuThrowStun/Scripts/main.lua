local UEHelpers = require("UEHelpers")

local WEAPON_ROOT = "/Game/Blueprints/LDIngredients/Weapons/MakeShift_OneHandedFamily/"
local THROWABLES = {
    { "Brick/", "BP_Weapon_Brick" },
    { "Brick/", "BP_Weapon_Brick_HardDisk" },
    { "ArtStatuette/", "BP_Weapon_ArtStatuette_01_A" },
    { "Doll/", "BP_Weapon_Doll_01_A" },
}

local function log(message)
    print("[SifuRandomThrowable] " .. message .. "\n")
end

if not EngineTickAvailable then
    log("EngineTick unavailable")
    return
end

local folder = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local pressAttack, bridgeError = package.loadlib(folder .. "ThrowableInputBridge.dll", "PressAttack")
local releaseAttack = package.loadlib(folder .. "ThrowableInputBridge.dll", "ReleaseAttack")
if not pressAttack or not releaseAttack then
    log("Input bridge unavailable: " .. tostring(bridgeError))
    return
end

local pending

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
                local world = controller:GetWorld()
                if valid(world) then return controller, pawn, world end
            end
        end
    end
end

local function canEquip(controller, pawn, world)
    return not controller.bShowMouseCursor
        and not UEHelpers.GetGameplayStatics():IsGamePaused(world)
        and not pawn:IsDead() and not pawn:BPF_IsDown() and not pawn:BPF_IsInCinematic()
        and valid(pawn.CameraComponentThird1) and not pawn.CameraComponentThird1:BPF_IsInCinematic()
end

local function findWeaponClass(entry)
    local name = entry[2]
    local path = WEAPON_ROOT .. entry[1] .. name .. "." .. name .. "_C"
    local class = StaticFindObject(path)
    if not valid(class) then
        local kismet = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
        local loaded, result = pcall(function()
            local softPath = kismet:MakeSoftClassPath(path)
            return kismet:LoadClassAsset_Blocking(kismet:Conv_SoftClassPathToSoftClassRef(softPath))
        end)
        if loaded then class = result end
        if not valid(class) then
            pcall(LoadAsset, path)
            class = StaticFindObject(path)
        end
    end
    return class
end

local function spawnWeapon(world, pawn, class)
    local position = pawn:K2_GetActorLocation()
    local forward = pawn:GetActorForwardVector()
    local location = {
        X = position.X + forward.X * 90,
        Y = position.Y + forward.Y * 90,
        Z = position.Z + 30,
    }
    return world:SpawnActor(class, location, pawn:K2_GetActorRotation())
end

local function attackAfterPickup(controller, pawn, world, weapon)
    local statics = UEHelpers.GetGameplayStatics()
    local state = { readyAt = statics:GetRealTimeSeconds(world) + 0.12 }
    pending = state
    local function update()
        if pending ~= state then return end
        local ok, err = xpcall(function()
            if not valid(world) then
                releaseAttack()
                pending = nil
                return
            end
            local now = statics:GetRealTimeSeconds(world)
            if state.pressedAt and not state.released then
                if now - state.pressedAt < 0.06 then
                    ExecuteInGameThreadAfterFrames(1, update)
                    return
                end
                releaseAttack()
                state.released = true
            end

            if not valid(controller) or not valid(pawn) or not same(controller.Pawn, pawn) then
                releaseAttack()
                pending = nil
                return
            end
            if state.released then
                if not same(pawn:BPF_GetPickedUpWeapon(), weapon) then
                    log("Throwable released")
                    pending = nil
                elseif now - state.pressedAt >= 1.0 then
                    log("Attack completed; item still held")
                    pending = nil
                else
                    ExecuteInGameThreadAfterFrames(1, update)
                end
                return
            end
            if not canEquip(controller, pawn, world)
                or not same(pawn:BPF_GetPickedUpWeapon(), weapon) then
                pending = nil
                return
            end
            if now < state.readyAt then
                ExecuteInGameThreadAfterFrames(1, update)
                return
            end
            pressAttack()
            state.pressedAt = now
            log("Sent one attack for " .. weapon:GetFName():ToString())
            ExecuteInGameThreadAfterFrames(1, update)
        end, debug.traceback)
        if not ok then
            releaseAttack()
            pending = nil
            log(tostring(err))
        end
    end
    ExecuteInGameThreadAfterFrames(1, update)
end

local function giveThrowable()
    if pending then return end
    local controller, pawn, world = localPlayer()
    if not pawn or not canEquip(controller, pawn, world) then return end
    if valid(pawn:BPF_GetPickedUpObject()) then
        log("Hands occupied")
        return
    end

    local start = math.random(#THROWABLES)
    local baseWeapon = StaticFindObject("/Script/Sifu.BaseWeapon")
    if not valid(baseWeapon) then error("BaseWeapon class unavailable") end

    for offset = 0, #THROWABLES - 1 do
        local entry = THROWABLES[(start + offset - 1) % #THROWABLES + 1]
        local class = findWeaponClass(entry)
        if valid(class) then
            local weapon = spawnWeapon(world, pawn, class)
            if valid(weapon) then
                if not weapon:IsA(baseWeapon) then
                    weapon:K2_DestroyActor()
                    log("Skipped incompatible asset " .. entry[2])
                else
                    local ok, err = pcall(function() pawn:BPF_PickUpObject(weapon, false) end)
                    if same(pawn:BPF_GetPickedUpWeapon(), weapon) then
                        log("Equipped " .. entry[2])
                        attackAfterPickup(controller, pawn, world, weapon)
                        return
                    end
                    if valid(weapon) then weapon:K2_DestroyActor() end
                    if not ok then error(err) end
                    log("Pickup failed for " .. entry[2])
                end
            else
                log("Spawn failed for " .. entry[2])
            end
        else
            log("Asset unavailable: " .. entry[2])
        end
    end
    log("No throwable could be equipped")
end

RegisterKeyBind(Key.V, function()
    ExecuteInGameThread(function()
        local ok, err = xpcall(giveThrowable, debug.traceback)
        if not ok then log(tostring(err)) end
    end, EGameThreadMethod.EngineTick)
end)

log("Ready. Press V to equip and throw a random throwable.")

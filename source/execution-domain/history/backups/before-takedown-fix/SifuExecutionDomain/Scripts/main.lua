local UEHelpers = require("UEHelpers")
local folder = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local function log(message) print("[SifuExecutionDomain] " .. message .. "\n") end
if not EngineTickAvailable then log("EngineTick unavailable"); return end
local native = {}
for _, name in ipairs({"Acquire", "Sustain", "Release", "PauseTransition", "ResumeTransition", "OrderState"}) do
    local fn, err = package.loadlib(folder .. "ExecutionBridge.dll", name)
    if not fn then log(name .. ": " .. tostring(err)); return end
    native[name] = fn
end
if native.Acquire(0, 0) ~= 1 then log("Unsupported executable; skill disabled"); return end
local Effects = dofile(folder .. "effects.lua")
local session
local lastToggle = -10
local lastToggleWorld
local function valid(o) return o ~= nil and type(o.IsValid) == "function" and o:IsValid() end
local function same(a,b) return valid(a) and valid(b) and a:GetAddress() == b:GetAddress() end
local statics = UEHelpers.GetGameplayStatics()
local function localPlayer()
    for _, c in ipairs(FindAllOf("PlayerController") or {}) do
        if valid(c) and valid(c.Player) and c.Player:GetClass():GetFName():ToString():find("LocalPlayer",1,true)
            and valid(c.Pawn) and c.Pawn:GetClass():GetFName():ToString() == "BP_FightingPlayer_C" then
            local w = c.Pawn:GetWorld()
            if valid(w) then return c,c.Pawn,w end
        end
    end
end
local function releaseRecord(r)
    if valid(r.target) then
        if r.handle then native.Release(r.target:GetAddress(),r.handle);r.handle=nil end
        if not r.target:IsDead() then
            for _, t in ipairs(r.transitions) do
                if valid(t) and valid(r.ai) then native.ResumeTransition(t:GetAddress(),r.ai:GetAddress()) end
            end
        end
    end
    r.transitions={}
end
local function stop(reason, immediate)
    local s=session
    if not s then return end
    session=nil
    for _,r in pairs(s.targets) do
        local ok,err=pcall(releaseRecord,r)
        if not ok then log("Cleanup: "..tostring(err)) end
    end
    Effects.stop(s.fx,immediate)
    log("OFF ("..reason..")")
end
local function eligible(s,target)
    if not valid(target) or same(target,s.pawn) or target.bHidden or target:IsDead()
        or target:IsActorBeingDestroyed() or not same(target:GetWorld(),s.world) or not valid(target.Controller) then return false end
    if not s.game:BPF_CanTargetFaction(s.pawn.m_eFaction,target.m_eFaction) then return false end
    local ai=target:GetAiComponent()
    if not valid(ai) then return false end
    local archetype=ai:BPF_GetArchetypeData()
    return valid(archetype) and not archetype.m_bIsBoss,ai
end
local transitionClass
local function suppressTransitions(r)
    if not valid(r.ai) then return end
    transitionClass=transitionClass or StaticFindObject("/Script/Sifu.AIPhaseTransitionTakedown")
    if not valid(transitionClass) then return end
    local list=r.ai.m_CurrentPhaseTransitions
    for i=1,#list do
        local t=list[i]
        if valid(t) and t:IsA(transitionClass) then
            local found=false
            for _,old in ipairs(r.transitions) do if same(old,t) then found=true;break end end
            if not found and native.PauseTransition(t:GetAddress(),r.ai:GetAddress())==1 then
                table.insert(r.transitions,t)
            end
        end
    end
end
local function scan(s)
    for _,target in ipairs(FindAllOf("FightingCharacter") or {}) do
        local accepted,ai=eligible(s,target)
        if accepted then
            local id=target:GetAddress()
            local r=s.targets[id]
            if not r or not same(r.target,target) then
                r={target=target,ai=ai,transitions={}};s.targets[id]=r
            end
            if (native.OrderState(id) & 3) == 0 then
                if r.handle and native.Sustain(id,r.handle)==0 then r.handle=nil end
                if not r.handle then
                    local handle=native.Acquire(id,s.pawn:GetAddress())
                    if handle>=0 then
                        r.handle=handle
                        log("Bound "..target:GetFName():ToString().." handle="..handle)
                    elseif r.error~=handle then r.error=handle;log("Deferred "..target:GetFName():ToString().." reason="..handle) end
                end
                if r.handle then suppressTransitions(r) end
            end
        end
    end
    for id,r in pairs(s.targets) do
        if not eligible(s,r.target) then releaseRecord(r);s.targets[id]=nil end
    end
end
local function toggle()
    local c,p,w=localPlayer()
    if not c or statics:IsGamePaused(w) or c.bShowMouseCursor then return end
    local now=statics:GetRealTimeSeconds(w)
    if not same(lastToggleWorld,w) then lastToggle=-10;lastToggleWorld=w end
    if now-lastToggle<0.35 then return end
    lastToggle=now
    if session then stop("4",false);return end
    if p:IsDead() or p:BPF_IsDown() or p:BPF_IsInCinematic() then return end
    local kismet=StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
    if valid(kismet) then log("Renderer ForwardShading="..tostring(kismet:GetConsoleVariableIntValue("r.ForwardShading"))) end
    local s={controller=c,pawn=p,world=w,game=UEHelpers.GetGameInstance(),mesh=p.Mesh,targets={},nextScan=0}
    if not valid(s.game) or not valid(s.mesh) then return end
    session=s
    s.fx=Effects.start(p,w)
    scan(s)
    log("ON (4 to close; X uses native takedowns)")
end
local function update()
    Effects.tick()
    local s=session
    if not s then return end
    if not valid(s.world) or not valid(s.pawn) or not valid(s.controller)
        or not same(s.controller.Pawn,s.pawn) or not same(s.pawn:GetWorld(),s.world)
        or not same(s.pawn.Mesh,s.mesh) or s.pawn:IsDead() then stop("left gameplay",true);return end
    if statics:IsGamePaused(s.world) or s.controller.bShowMouseCursor then return end
    local executing=native.OrderState(s.pawn:GetAddress()) & 1 ~= 0
    if s.pawn:BPF_IsInCinematic() and not executing then stop("cinematic",true);return end
    Effects.update(s.fx,executing)
    local now=statics:GetRealTimeSeconds(s.world)
    if now>=s.nextScan then scan(s);s.nextScan=now+0.15 end
end
local function guarded(fn)
    local ok,err=xpcall(fn,debug.traceback)
    if not ok then log(tostring(err));stop("error",true) end
end
RegisterKeyBind(Key.FOUR,function()
    ExecuteInGameThread(function()guarded(toggle)end,EGameThreadMethod.EngineTick)
end)
LoopInGameThreadAfterFrames(1,function()guarded(update)end)
log("Ready. Press 4 for Golden War God.")

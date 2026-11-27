"""Exercise the actual Lua coordinator with a deterministic fake engine/native boundary."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/yang-moves/test-runtime'))
from lupa.lua54 import LuaRuntime

lua=LuaRuntime()
lua.execute(r'''
EngineTickAvailable=true; EGameThreadMethod={EngineTick=1};Key={FOUR=4}
now=1;paused=false;order={};held={};released=0;nextHandle=0;fxStarts=0;fxStops=0
function object(id,name)
  local o={id=id,alive=true,name=name or 'Object'}
  function o:IsValid()return self.alive end
  function o:GetAddress()return self.id end
  function o:GetFName()return {ToString=function()return self.name end}end
  function o:GetClass()return self end
  return o
end
world=object(1);camera=object(2);mesh=object(3);game=object(4)
function game:BPF_CanTargetFaction(a,b)return a~=b end
player=object(10,'BP_FightingPlayer_C');player.Mesh=mesh;player.CameraComponentThird1=camera;player.m_eFaction=0
function player:IsDead()return self.dead or false end
function player:BPF_IsDown()return false end
function player:BPF_IsInCinematic()return self.cinematic or false end
function player:GetWorld()return world end
controller=object(11);controller.Pawn=player;controller.Player=object(12,'LocalPlayer')
function enemy(id,boss)
  local e=object(id,'Enemy'..id);e.Controller=object(id+100);e.m_eFaction=1
  e.ai=object(id+200);e.ai.m_CurrentPhaseTransitions={}
  e.hit=object(id+400)
  function e:GetComponentByClass()return self.hit end
  e.ai.archetype=object(id+300);e.ai.archetype.m_bIsBoss=boss or false
  function e.ai:BPF_GetArchetypeData()return self.archetype end
  function e:GetAiComponent()return self.ai end
  function e:GetWorld()return world end
  function e:IsDead()return self.dead or false end
  function e:IsActorBeingDestroyed()return false end
  return e
end
enemies={enemy(20),enemy(21,true)}
local gs={}
function gs:IsGamePaused()return paused end
function gs:GetRealTimeSeconds()return now end
package.preload.UEHelpers=function()return {GetGameplayStatics=function()return gs end,GetGameInstance=function()return game end}end
local funcs={
  Acquire=function(t,p)if t==0 then return 1 end;nextHandle=nextHandle+1;held[t]=nextHandle;return nextHandle end,
  Sustain=function(t,h)return held[t]==h and 1 or 0 end,
  Release=function(t,h)assert(held[t]==h);held[t]=nil;released=released+1;return 1 end,
  OrderState=function(t)return order[t] or 0 end,
  PauseTransition=function()return 0 end,ResumeTransition=function()return 0 end
  ,SameWorld=function(t)return t~=24 and 1 or 0 end,Inspect=function()return 1793 end
}
package.loadlib=function(_,name)return funcs[name]end
dofile=function()return {start=function()fxStarts=fxStarts+1;return {}end,
  stop=function()fxStops=fxStops+1 end,update=function()end,tick=function()end}end
function FindAllOf(name)if name=='PlayerController'then return {controller}else return enemies end end
function StaticFindObject(path)if path=='/Script/Sifu.HitComponent'then return object(2000)end;return nil end
function RegisterKeyBind(_,callback)toggle=callback end
function ExecuteInGameThread(callback)callback()end
function LoopInGameThreadAfterFrames(_,callback)tick=callback end
function press()now=now+1;toggle()end
''')
script=Path(__file__).parent/'SifuExecutionDomain/Scripts/main.lua'
lua.compile(script.read_text(encoding='utf-8'),name='@'+script.as_posix())()
lua.execute(r'''
press();assert(held[20] and not held[21]);assert(fxStarts==1)
now=now+61;tick();assert(held[20]);assert(released==0)
table.insert(enemies,enemy(22));tick();now=now+1;tick();assert(held[22])
-- Streamed enemies have a different outer UWorld but the same native OwningWorld.
local streamed=enemy(23);function streamed:GetWorld()return object(9000)end
table.insert(enemies,streamed);table.insert(enemies,enemy(24))
now=now+1;tick();assert(held[23] and not held[24])
paused=true;press();assert(released==0);paused=false
press();assert(not held[20] and not held[22] and not held[23]);assert(released==3 and fxStops==1)
press();player.dead=true;tick();assert(fxStops==2);player.dead=false
now=1;world=object(1000);toggle();assert(fxStarts==3) -- new world's debounce clock resets
controller.Pawn=object(1001);tick();assert(fxStops==3)
print('PASS: streaming level enrollment, other-world exclusion, boss exclusion, persistence, spawn enrollment, pause, toggle, death, world clock, pawn replacement')
''')

local c=...
local pc,p,w=c.player()
if not p then return 'No player yet' end
c.log('PlayerWorld '..w:GetFullName())
for _,t in ipairs(FindAllOf('FightingCharacter') or {}) do
 if t:IsValid() and not t.bHidden and t:GetAddress()~=p:GetAddress() then
  c.log('Membership '..t:GetFName():ToString()..' luaWorld='..t:GetWorld():GetFullName()..' nativeSame='..c.native.SameWorld(t:GetAddress(),p:GetAddress()))
 end
end

-- Not shipped: execute each explicitly authored local diagnostic request once.
local folder=debug.getinfo(1,"S").source:sub(2):match("^(.*[/\\])")
local last
return function(context)
    local file=io.open(folder.."request.lua","r")
    if not file then return end
    local source=file:read("*a");file:close()
    if source==last then return end
    last=source
    local chunk,err=load(source,"@execution-domain-local-probe","t",_ENV)
    if not chunk then context.log("Probe compile: "..tostring(err));return end
    local ok,result=xpcall(function()return chunk(context)end,debug.traceback)
    context.log("Probe "..(ok and "OK " or "ERROR ")..tostring(result))
end

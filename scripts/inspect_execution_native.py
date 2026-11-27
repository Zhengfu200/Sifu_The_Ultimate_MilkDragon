"""Inspect image-matched shipping symbols; never attaches to or writes game memory."""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
IMAGE = Path(r'D:\Sifu\Sifu\Binaries\Win64\Sifu-Win64-Shipping.exe')
OUT = ROOT / 'build/execution-domain'
OUT.mkdir(parents=True, exist_ok=True)
class Symbol(c.Structure):
    _fields_ = [('SizeOfStruct',w.ULONG),('TypeIndex',w.ULONG),('Reserved',c.c_ulonglong*2),
        ('Index',w.ULONG),('Size',w.ULONG),('ModBase',c.c_ulonglong),('Flags',w.ULONG),
        ('Value',c.c_ulonglong),('Address',c.c_ulonglong),('Register',w.ULONG),
        ('Scope',w.ULONG),('Tag',w.ULONG),('NameLen',w.ULONG),('MaxNameLen',w.ULONG),('Name',c.c_char*1)]
dbg = c.WinDLL('dbghelp', use_last_error=True)
handle = c.c_void_p(0x53494655)
dbg.SymInitialize.argtypes = [c.c_void_p,c.c_char_p,w.BOOL]
dbg.SymSetOptions(0x2 | 0x10 | 0x80000)
assert dbg.SymInitialize(handle,str(IMAGE.parent).encode(),False)
dbg.SymLoadModuleEx.argtypes=[c.c_void_p,c.c_void_p,c.c_char_p,c.c_char_p,c.c_ulonglong,w.DWORD,c.c_void_p,w.DWORD]
dbg.SymLoadModuleEx.restype=c.c_ulonglong
base = dbg.SymLoadModuleEx(handle,None,str(IMAGE).encode(),None,0x140000000,0,None,0)
assert base, c.get_last_error()
callback_type=c.WINFUNCTYPE(w.BOOL,c.POINTER(Symbol),w.ULONG,c.c_void_p)
symbols={}
@callback_type
def collect(ptr,size,context):
    s=ptr.contents
    name=c.string_at(c.addressof(s)+Symbol.Name.offset,s.NameLen).decode(errors='replace')
    symbols[name]={'address':s.Address,'rva':s.Address-base,'size':s.Size,'type':s.TypeIndex,'tag':s.Tag}
    return True
dbg.SymEnumSymbols.argtypes=[c.c_void_p,c.c_ulonglong,c.c_char_p,callback_type,c.c_void_p]
patterns=sys.argv[1:]
type_mode=bool(patterns and patterns[0]=='--types')
address_mode=bool(patterns and patterns[0]=='--address')
if address_mode:
    dbg.SymFromAddr.argtypes=[c.c_void_p,c.c_ulonglong,c.POINTER(c.c_ulonglong),c.c_void_p]
    for value in patterns[1:]:
        addr=int(value,0);addr=addr+base if addr<base else addr
        buffer=c.create_string_buffer(4096);s=Symbol.from_buffer(buffer);s.SizeOfStruct=c.sizeof(Symbol);s.MaxNameLen=3900
        displacement=c.c_ulonglong()
        if dbg.SymFromAddr(handle,addr,c.byref(displacement),buffer):collect(c.cast(buffer,c.POINTER(Symbol)),0,None)
for pattern in ([] if type_mode or address_mode else patterns or ['*Takedown*','*StructureBroken*','*FightingState*','*Boss*']):
    assert dbg.SymEnumSymbols(handle,base,pattern.encode(),collect,None),c.get_last_error()
cache=OUT/'symbols.json'
previous=json.loads(cache.read_text()) if cache.exists() else {}
previous.update(symbols)
cache.write_text(json.dumps(previous,indent=2))
for name,s in symbols.items():
    if s['size'] and s['tag']==5:
        print(f"{s['rva']:08x} {s['size']:5} {name}")
if type_mode:
    dbg.SymGetTypeInfo.argtypes=[c.c_void_p,c.c_ulonglong,w.ULONG,c.c_int,c.c_void_p]
    dbg.SymGetTypeFromName.argtypes=[c.c_void_p,c.c_ulonglong,c.c_char_p,c.c_void_p]
    def info(t,what,kind=w.ULONG):
        v=kind()
        return v.value if dbg.SymGetTypeInfo(handle,base,t,what,c.byref(v)) else None
    def tname(t):
        p=c.c_void_p()
        if dbg.SymGetTypeInfo(handle,base,t,1,c.byref(p)):
            v=c.wstring_at(p);c.windll.kernel32.LocalFree(c.c_void_p(p.value));return v
    def children(t):
        n=info(t,13) or 0
        b=(w.ULONG*(n+2))();b[0]=n
        if n and dbg.SymGetTypeInfo(handle,base,t,7,b):return list(b)[2:]
        return []
    def describe(t,depth=0):
        if depth>5:return str(t)
        tag=info(t,0);name=tname(t)
        if name:return name
        tid=info(t,4)
        if tag==14:return describe(tid,depth+1)+'*'
        if tag==13:return describe(tid,depth+1)+'('+','.join(describe(x,depth+1) for x in children(t))+')'
        if tag==20:return describe(tid,depth+1)
        if tag==16:return 'base'+str(info(t,5))+':'+str(info(t,2,c.c_ulonglong))
        return f'tag{tag}/type{t}'
    types={}
    for name in patterns[1:]:
        buffer=c.create_string_buffer(4096);s=Symbol.from_buffer(buffer);s.SizeOfStruct=c.sizeof(Symbol);s.MaxNameLen=3900
        if not dbg.SymGetTypeFromName(handle,base,name.encode(),buffer):print('MISSING',name);continue
        t=s.TypeIndex;rows=[]
        print(name,'size',info(t,2,c.c_ulonglong),'type',t)
        for x in children(t):
            tag=info(x,0);tid=info(x,4);offset=info(x,10)
            row={'name':tname(x),'tag':tag,'offset':offset,'type':describe(tid) if tid else None}
            if tag==7:
                raw=c.create_string_buffer(24)
                if dbg.SymGetTypeInfo(handle,base,x,11,raw):
                    vt=int.from_bytes(raw.raw[:2],'little')
                    width={2:2,3:4,16:1,17:1,18:2,19:4,20:8,21:8}.get(vt,8)
                    row['value']=int.from_bytes(raw.raw[8:8+width],'little',signed=vt in (2,3,16,20))
            rows.append(row)
            print(json.dumps(row))
        types[name]=rows
    (OUT/'types.json').write_text(json.dumps(types,indent=2))
dbg.SymCleanup(handle)

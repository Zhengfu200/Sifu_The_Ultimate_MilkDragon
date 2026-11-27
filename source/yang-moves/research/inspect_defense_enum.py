import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
dbg=c.WinDLL(r"D:\Sifu\Sifu\Binaries\Win64\dbghelp.dll")
kernel=c.WinDLL("kernel32")
kernel.GetCurrentProcess.restype=w.HANDLE
process=kernel.GetCurrentProcess()
dbg.SymInitializeW.argtypes=[w.HANDLE,w.LPCWSTR,w.BOOL]
dbg.SymInitializeW.restype=w.BOOL
dbg.SymLoadModuleExW.argtypes=[w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_ulonglong,w.DWORD,c.c_void_p,w.DWORD]
dbg.SymLoadModuleExW.restype=c.c_ulonglong
dbg.SymFromName.argtypes=[w.HANDLE,c.c_char_p,c.c_void_p]
dbg.SymFromName.restype=w.BOOL
class Symbol(c.Structure):
    _fields_=[("SizeOfStruct",w.ULONG),("TypeIndex",w.ULONG),("Reserved",c.c_ulonglong*2),("Index",w.ULONG),("Size",w.ULONG),("ModBase",c.c_ulonglong),("Flags",w.ULONG),("Value",c.c_ulonglong),("Address",c.c_ulonglong),("Register",w.ULONG),("Scope",w.ULONG),("Tag",w.ULONG),("NameLen",w.ULONG),("MaxNameLen",w.ULONG),("Name",c.c_char*1024)]
if not dbg.SymInitializeW(process,r"D:\Sifu\Sifu\Binaries\Win64",False): raise RuntimeError("SymInitialize")
base=dbg.SymLoadModuleExW(process,None,r"D:\Sifu\Sifu\Binaries\Win64\Sifu-Win64-Shipping.exe",None,0,0,None,0)
if not base: raise RuntimeError("SymLoadModule")
symbol=Symbol()
symbol.SizeOfStruct=88
symbol.MaxNameLen=1024
name=b"?Z_Construct_UEnum_Sifu_EHitBoxDefenseMatrix@@YAPEAVUEnum@@XZ"
if not dbg.SymFromName(process,name,c.byref(symbol)) and not dbg.SymFromName(process,b"Z_Construct_UEnum_Sifu_EHitBoxDefenseMatrix",c.byref(symbol)): raise RuntimeError("SymFromName")
rva=symbol.Address-base
print("Defense enum constructor RVA",hex(rva),"size",symbol.Size)
Path(r"build/yang-moves/defense-enum-rva.txt").write_text(str(rva))


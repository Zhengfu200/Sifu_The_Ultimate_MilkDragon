import json, re, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
symbols=json.loads((root/'build/execution-domain/symbols.json').read_text())
names={v['address']:k for k,v in symbols.items()}
for pattern in sys.argv[1:]:
    for name,s in symbols.items():
        if not re.search(pattern,name) or not s['size'] or s['tag']!=5: continue
        text=subprocess.check_output(['D:/mingw64/bin/objdump.exe','-d','-M','intel','--no-show-raw-insn',f"--start-address={s['address']}",f"--stop-address={s['address']+s['size']}",'D:/Sifu/Sifu/Binaries/Win64/Sifu-Win64-Shipping.exe'],text=True)
        print('\n; '+name)
        for line in text.splitlines():
            m=re.search(r'(?:call|jmp)\s+(0x)?([0-9a-f]{9,})',line)
            if m and int(m[2],16) in names: line+=' ; '+names[int(m[2],16)]
            if re.match(r'\s*[0-9a-f]+:',line):print(line)

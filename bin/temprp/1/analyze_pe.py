import pathlib, struct, hashlib, re
p=pathlib.Path('decoded_payload_pe.bin'); b=p.read_bytes()
print('size', len(b), 'sha256', hashlib.sha256(b).hexdigest())
e_lfanew=struct.unpack_from('<I',b,0x3c)[0]
print('e_lfanew',hex(e_lfanew), b[e_lfanew:e_lfanew+4])
coff=e_lfanew+4
Machine,NumSections,TimeDate,PtrSym,NumSym,OptSize,Chars=struct.unpack_from('<HHIIIHH',b,coff)
print(hex(Machine), NumSections, hex(TimeDate), hex(Chars), 'optsize', OptSize)
opt=coff+20
magic=struct.unpack_from('<H',b,opt)[0]
entry=struct.unpack_from('<I',b,opt+16)[0]; imagebase=struct.unpack_from('<I',b,opt+28)[0]; sizeimg=struct.unpack_from('<I',b,opt+56)[0]
subsys=struct.unpack_from('<H',b,opt+68)[0]
print('magic',hex(magic),'entry',hex(entry),'imagebase',hex(imagebase),'sizeimg',hex(sizeimg),'subsys',subsys)
sec_off=opt+OptSize
for i in range(NumSections):
    off=sec_off+i*40
    name=b[off:off+8].rstrip(b'\0').decode('latin1')
    vs,va,rawsz,rawptr,_,_,_,_,chars=struct.unpack_from('<IIIIIIHHI',b,off+8)
    print(i,name,hex(va),hex(vs),hex(rawptr),hex(rawsz),hex(chars))
print('ascii strings:')
seen=set()
for s in re.findall(rb'[ -~]{5,}', b):
    sl=s.lower()
    if any(x in sl for x in [b'http',b'.dll',b'.exe',b'win',b'user',b'kernel',b'advapi',b'socket',b'reg',b'cmd',b'run',b'mutex',b'crypt',b'virtual',b'process',b'url',b'host',b'agent',b'connect']):
        if s not in seen:
            seen.add(s); print(s[:200])

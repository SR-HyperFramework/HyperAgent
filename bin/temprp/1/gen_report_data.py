import pathlib, hashlib, re, struct, json
paths=[r'E:\CTF\ResearchCase\Sample\5175b1720fe3bc568f7857b72b960260ad3982f41366ce3372c04424396df6fe','decoded_payload.bin','decoded_payload_pe.bin']
for x in paths:
    p=pathlib.Path(x); b=p.read_bytes()
    print(x, len(b), hashlib.md5(b).hexdigest(), hashlib.sha1(b).hexdigest(), hashlib.sha256(b).hexdigest())
# parse payload PE rough
b=pathlib.Path('decoded_payload_pe.bin').read_bytes(); e=struct.unpack_from('<I',b,0x3c)[0]; coff=e+4
print('PE sig off',hex(e),b[e:e+4])
print('COFF',struct.unpack_from('<HHIIIHH',b,coff))
opt=coff+20
print('entry,imagebase,sizeimg', [hex(x) for x in (struct.unpack_from('<I',b,opt+16)[0], struct.unpack_from('<I',b,opt+28)[0], struct.unpack_from('<I',b,opt+56)[0])])
# extract focused strings
ss=sorted(set(s.decode('latin1','ignore') for s in re.findall(rb'[ -~]{3,}', b)))
keys=['ADVAPI','USER32','KERNEL','ntdll','Reg','Wow64','Nt','Rtl','HTTP','Crypt','sha','aes','sprng','sysnative','system32','process','MessageBox','Window','srv.dll']
for s in ss:
    if any(k.lower() in s.lower() for k in keys): print(s)

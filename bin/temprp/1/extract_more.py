import pathlib,re
b=pathlib.Path('decoded_payload_pe.bin').read_bytes()
for enc,data in [('ascii',b),('utf16le',b.decode('utf-16le','ignore').encode('latin1','ignore'))]:
    ss=sorted(set(re.findall(rb'[ -~]{4,}', data)))
    print('---',enc,len(ss))
    for s in ss[:1000]:
        text=s.decode('latin1','ignore')
        if any(k in text.lower() for k in ['http','dll','reg','crypt','process','socket','connect','server','srv','user','window','key','run','create','thread','file','temp','appdata','cmd','exe','mutex']):
            print(text)

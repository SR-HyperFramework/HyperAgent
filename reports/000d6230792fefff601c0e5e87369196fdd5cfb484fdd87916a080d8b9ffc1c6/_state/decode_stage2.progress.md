# Decode Stage-2 PE — Progress

## What's been done

1. **Config block read** at shellcode offset 0x6A5 (7 dwords, 28 bytes):
   - [0] skip_offset = 0
   - [1] skip_size = 0
   - [2] pe_offset = 0x00B20400
   - [3] mapping_high = 0x05200000
   - [4] size = 0x00040000
   - [5] field = 0x89AFFB00
   - [6] key_component = 0x00005A89 (3 bytes at 0x6BD, zero-padded)

2. **Key computation**: key = [ebp+0x70] XOR 0x7845EA91 = 0x00005A89 XOR 0x7845EA91 = 0x7845B018

3. **Decode algorithm** (function at 0x4DA):
   - Write pe_offset to [esi+0x3C] (fix e_lfanew)
   - Skip pe_offset/4 dwords (skip PE header area)
   - For each dword: out = bswap(src) ^ key; key = src
   - sub ecx, 3; loop (each iteration consumes 4 dwords from ecx)

4. **Key insight**: The decode function operates on the **mapped view of the original PE file** (from CreateFileMappingA/MapViewOfFile), NOT on the 0x6AC-byte buffer copied from the shellcode. The config block values (pe_offset=0x00B20400, size=0x00040000) are too large for the 390KB original sample.

## What's unresolved

- The pe_offset = 0x00B20400 (11,673,600) is much larger than the original sample (390,144 bytes). This suggests either:
  a) The config block is at a different offset than assumed
  b) The pe_offset field is not what I think it is
  c) The decode operates on a different data source
- The key component at 0x6BD is truncated (only 3 bytes available at end of file)
- The decode with key 0x7845B018 on the 0x6AC-byte buffer didn't produce a valid PE
- The decode with key 0x22CC456A (original sample key) on the 0x6AC-byte buffer also didn't produce a valid PE

## Next steps to try

1. **Re-examine the config block alignment**: The config might start at 0x6A2 (not 0x6A5), shifting all field offsets by -3
2. **Try decode on the original PE file's overlay/rdata section** instead of the shellcode buffer
3. **Re-examine the decode function's esi parameter**: At call 0xF0, esi might point to the mapped PE view, not the buffer
4. **Try the original sample's key 0x22CC456A** on the original PE file's data sections
5. **Check if the decode is actually a different algorithm** than what was analyzed (the sub ecx,3 + loop pattern is unusual)

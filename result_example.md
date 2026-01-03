
## Group 1 - Compiler
### Fixed PE Header Broken 
```
{
  "filename": "_chal1.bin",
  "die_result": {
    "parsed": {
      "file_class": "PE64",
      "packer": null,
      "compiler": null,
      "language": "C/C++",
      "library": null,
      "tool": null,
      "malware": null
    },
    "entropy": 3.93248
  }
}
```

```
{
  "filename": "_dump.exe",
  "die_result": {
    "parsed": {
      "file_class": "PE64",
      "packer": "Microsoft Linker(14.36.34435)",
      "compiler": "Microsoft Visual C/C++(19.36.34435)[LTCG/C++]",
      "language": "C++",
      "library": "Microsoft C/C++ Runtime[dynamic]",
      "tool": "Visual Studio(2022, v17.6)",
      "malware": null
    },
    "entropy": 4.93502
  }
}
```
### UPX Packed
```
{
  "filename": "ida",
  "die_result": {
    "parsed": {
      "file_class": "PE32",
      "packer": "Compressed or packed data[EntryPoint + Imports like UPX (v2.90-3.XX) + Sections like UPX + Sections collision (\"UPX\") + \"pushal\" at EP + Section 1 (\"UPX1\") compressed]",
      "compiler": "Microsoft Visual C/C++(19.36.32548)[C++]",
      "language": "C++",
      "library": null,
      "tool": "Visual Studio(2022, v17.6)",
      "malware": null
    },
    "entropy": 6.76485
  }
}
```
### non-Packed (normal)
```
{
  "filename": "sample",
  "die_result": {
    "parsed": {
      "file_class": "PE64",
      "packer": "Microsoft Linker(14.36.34435)",
      "compiler": "Microsoft Visual C/C++(19.36.34435)[LTCG/C++]",
      "language": "C++",
      "library": "Microsoft C/C++ Runtime[dynamic]",
      "tool": "Visual Studio(2022, v17.6)",
      "malware": null
    },
    "entropy": 5.82467
  }
}
```

```
{
  "filename": "sample",
  "die_result": {
    "parsed": {
      "file_class": "PE64",
      "packer": "Microsoft Linker(14.25.28614)",
      "compiler": "Microsoft Visual C/C++(19.25.28614)[LTCG/C++]",
      "language": "C++",
      "library": "Microsoft C/C++ Runtime[dynamic]",
      "tool": "Visual Studio(2019, v16.5)",
      "malware": null
    },
    "entropy": 5.5221
  }
}
```

## Group 2 - Runtime
### Non-Packed + Non-Obfuscated
```
{
  "filename": "mbsa",
  "die_result": {
    "parsed": {
      "file_class": "PE32",
      "packer": "Microsoft Linker(8.0)",
      "compiler": "VB.NET",
      "language": "VB.NET",
      "library": ".NET Framework(CLR v4.0.30319)",
      "tool": null,
      "malware": "VenomRAT(6.X)"
    },
    "entropy": 5.44884
  }
}
```

```
{
  "filename": "ntoskrnl",
  "die_result": {
    "parsed": {
      "file_class": "PE32",
      "packer": "Microsoft Linker(11.0)",
      "compiler": "VB.NET",
      "language": "VB.NET",
      "library": ".NET Framework(Legacy, CLR v4.0.30319)",
      "tool": null,
      "malware": "XWorm(3.0-5.0)"
    },
    "entropy": 5.5859
  }
}
```

```

```

## Group 3 - Interpreter + Unsorted
### UPX Packed
```
{
  "filename": "chall",
  "die_result": {
    "parsed": {
      "file_class": "ELF64",
      "packer": "UPX(5.01)[NRV,brute]",
      "compiler": null,
      "language": null,
      "library": null,
      "tool": null,
      "malware": null
    },
    "entropy": 7.01524
  }
}
```

```
Response: {'filename': 'script.js', 'die_result': {'parsed': {'file_class': 'Binary', 'packer': None, 'compiler': None, 'language': 'JavaScript', 'library': None, 'tool': None}}}
```

```
Response: {'filename': 'vault.wasm', 'die_result': {'parsed': {'file_class': 'Binary', 'packer': None, 'compiler': None, 'language': None, 'library': None, 'tool': None}}}
```
### Python
#### Build with framework like Cython
```
{
  "filename": "dec_pb.dll",
  "die_result": {
    "parsed": {
      "file_class": "PE64",
      "packer": "Compressed or packed data[Strange overlay]",
      "compiler": "Microsoft Visual C/C++(19.36.34808)[C]",
      "language": "Python",
      "library": null,
      "tool": "Visual Studio(2022, v17.6)",
      "malware": null
    },
    "entropy": 7.99663
  }
}
```

#### Build with framework like PyInstaller
```
{
  "filename": "pypain",
  "die_result": {
    "parsed": {
      "file_class": "ELF64",
      "packer": "PyInstaller",
      "compiler": "GCC((GNU) 4.8.5 20150623 (Red Hat 4.8.5-44))",
      "language": "Python",
      "library": "GLIBC(2.7)[EXEC AMD64-64]",
      "tool": null,
      "malware": null
    },
    "entropy": 7.9971
  }
}
```

### Script as text
```
{
  "filename": "decryptor.ps1",
  "die_result": {
    "parsed": {
      "file_class": "Binary",
      "packer": null,
      "compiler": null,
      "language": "PowerShell Script[by extension]",
      "library": null,
      "tool": null,
      "malware": null
    },
    "entropy": 5.22601
  }
}
```


## Group 4 - Unsupported
```
Response: {'filename': 'vm', 'die_result': {'parsed': {'file_class': 'ELF64', 'packer': None, 'compiler': 'GCC(3.X)', 'language': 'C', 'library': 'GLIBC(2.34)[DYN AMD64-64]', 'tool': None, 'malware': None}}}
```

```
{
  "filename": "chall_unp",
  "die_result": {
    "parsed": {
      "file_class": "ELF64",
      "packer": null,
      "compiler": "GCC((GNU) 15.1.1 20250425)",
      "language": "C",
      "library": "GLIBC(2.4)[DYN AMD64-64]",
      "tool": null,
      "malware": null
    },
    "entropy": 1.89293
  }
}
```

```
{
  "filename": "helper",
  "die_result": {
    "parsed": {
      "file_class": "ELF64",
      "packer": null,
      "compiler": "GCC((Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0)",
      "language": "C",
      "library": "GLIBC(2.4)[DYN AMD64-64]",
      "tool": null,
      "malware": null
    },
    "entropy": 1.75325
  }
}
```
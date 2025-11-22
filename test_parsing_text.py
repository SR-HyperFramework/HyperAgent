import unittest
from app.services.die_service import parse_die_text_output

class TestDIETextParsing(unittest.TestCase):
    def test_parsing(self):
        mock_text = """[HEUR/About] Generic Heuristic Analysis by DosX (@DosX_dev)
[HEUR] Scanning has begun!
[HEUR] Scanning to programming language has started!
[HEUR/Any] Mangler detected -> "msvcp140.dll", at function "sputc"
[HEUR/Any] C++ library present -> "msvcp140.dll"
[HEUR/Any] C++ language detected!
[HEUR] Scan completed.
PE64
    Operation system: Windows(Vista)[AMD64, 64-bit, Console]
    Linker: Microsoft Linker(14.36.34435)
    Compiler: Microsoft Visual C/C++(19.36.34435)[LTCG/C++]
    Language: C++
    Library: Microsoft C/C++ Runtime[dynamic]
    Tool: Visual Studio(2022, v17.6)
"""
        
        result = parse_die_text_output(mock_text)
        
        self.assertEqual(result["file_class"], "PE64")
        # Linker is mapped to packer in my logic if packer is missing
        self.assertEqual(result["packer"], "Microsoft Linker(14.36.34435)") 
        self.assertEqual(result["compiler"], "Microsoft Visual C/C++(19.36.34435)[LTCG/C++]")
        self.assertEqual(result["language"], "C++")
        self.assertEqual(result["tool"], "Visual Studio(2022, v17.6)")

if __name__ == '__main__':
    unittest.main()

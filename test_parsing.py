import unittest
from app.services.die_service import parse_die_output

class TestDIEParsing(unittest.TestCase):
    def test_parsing(self):
        mock_json = {
            "detects": [
                {
                    "filetype": "PE32",
                    "values": [
                        {"type": "Packer", "name": "UPX", "string": "3.96"},
                        {"type": "Compiler", "name": "Microsoft Visual C++", "string": "2019"},
                        {"type": "Language", "name": "C++", "string": ""}
                    ]
                }
            ]
        }
        
        result = parse_die_output(mock_json)
        
        self.assertEqual(result["file_class"], "PE32")
        self.assertEqual(result["packer"], "UPX 3.96")
        self.assertEqual(result["compiler"], "Microsoft Visual C++ 2019")
        self.assertEqual(result["language"], "C++")

if __name__ == '__main__':
    unittest.main()

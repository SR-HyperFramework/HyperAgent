import unittest
from unittest.mock import MagicMock, patch
from app.services.die_service import run_die

class TestDIEEntropyIntegration(unittest.TestCase):
    @patch('app.services.die_service.subprocess.run')
    @patch('app.services.die_service.shutil.which')
    def test_run_die_with_entropy(self, mock_which, mock_run):
        mock_which.return_value = "/path/to/diec"
        
        # Mock responses for two subprocess calls
        mock_info = MagicMock()
        mock_info.returncode = 0
        mock_info.stdout = "PE64\nCompiler: GCC"
        
        mock_entropy = MagicMock()
        mock_entropy.returncode = 0
        mock_entropy.stdout = "Entropy: 7.5"
        
        mock_run.side_effect = [mock_info, mock_entropy]
        
        result = run_die("dummy_path")
        
        self.assertEqual(result["parsed"]["file_class"], "PE64")
        self.assertEqual(result["parsed"]["compiler"], "GCC")
        self.assertEqual(result["entropy"], 7.5)

if __name__ == '__main__':
    unittest.main()

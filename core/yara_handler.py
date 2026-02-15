import yara
import os
from typing import List, Dict, Any

class YaraHandler:
    def __init__(self, rules_path: str):
        self.rules_path = rules_path
        self.rules = self._compile_rules()

    def _compile_rules(self):
        """
        Compiles all .yar files in the specified directory.
        Tries to compile all at once. If fails, tries individually to filter out bad rules.
        """
        filepaths = {}
        if not os.path.exists(self.rules_path):
            print(f"[WARN] YARA rules directory not found: {self.rules_path}")
            return None

        # 1. Collect all candidate files
        candidates = {}
        for root, dirs, files in os.walk(self.rules_path):
            for file in files:
                if file.endswith(".yar") or file.endswith(".yara"):
                    full_path = os.path.join(root, file)
                    # Use relative path as key
                    namespace = os.path.relpath(full_path, self.rules_path).replace("\\", "/") #.replace(".", "_")
                    candidates[namespace] = full_path
        
        print(f"[DEBUG] Found {len(candidates)} rule files in {self.rules_path}")
        if not candidates:
            return None

        # 2. Try compiling all at once (fastest)
        try:
            return yara.compile(filepaths=candidates)
        except yara.SyntaxError as e:
            print(f"[WARN] Batch compilation failed. Retrying individually... Error: {e}")
        except Exception as e:
            print(f"[WARN] Batch compilation error: {e}")

        # 3. Fallback: Compile individually to skip bad files
        valid_rules = {}
        for ns, path in candidates.items():
            try:
                # Test compile single file
                yara.compile(filepath=path)
                valid_rules[ns] = path
            except Exception as e:
                print(f"[WARN] Skipping bad rule {ns}: {e}")
        
        if valid_rules:
            print(f"[INFO] Successfully compiled {len(valid_rules)}/{len(candidates)} rules.")
            try:
                return yara.compile(filepaths=valid_rules)
            except Exception as e:
                print(f"[ERROR] Final compilation failed: {e}")
                return None
        return None

    def match(self, target_path: str) -> List[Dict[str, Any]]:
        """
        Scans a file against compiled rules.
        """
        if not self.rules:
            return []
        
        try:
            matches = self.rules.match(target_path)
            results = []
            for match in matches:
                results.append({
                    "rule": match.rule,
                    "namespace": match.namespace,
                    "tags": match.tags,
                    "meta": match.meta
                })
            return results
        except Exception as e:
            print(f"[ERROR] YARA Scan Error: {e}")
            return []

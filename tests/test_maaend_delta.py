"""生成器与字节重建契约；不下载或运行 MaaEnd。"""

import hashlib
import random
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from copilot_data.zip_delta import apply_patch, create_patch


class MaaEndDeltaTests(unittest.TestCase):
    def test_rebuilds_exact_target_with_changed_headers_and_removed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, target, patch, rebuilt = (
                root / name
                for name in ("base.zip", "target.zip", "patch.zip", "rebuilt.zip")
            )
            unchanged = random.Random(13).randbytes(1024 * 1024)
            with zipfile.ZipFile(
                baseline, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr("obsolete.txt", "removed")
                archive.writestr("resource/large.bin", unchanged)
                archive.writestr("interface.json", '{"version":"v1.0.0"}')
            with zipfile.ZipFile(
                target, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr("interface.json", '{"version":"v1.0.1"}')
                archive.writestr("resource/large.bin", unchanged)
                archive.writestr("added.txt", "new")
                archive.comment = b"different archive metadata"
            create_patch(baseline, target, patch)
            repeated = root / "repeated.zip"
            create_patch(baseline, target, repeated)
            self.assertEqual(patch.read_bytes(), repeated.read_bytes())
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            size = target.stat().st_size
            apply_patch(baseline, patch, rebuilt, size, digest, threading.Event())
            self.assertEqual(rebuilt.read_bytes(), target.read_bytes())
            self.assertLess(patch.stat().st_size, size // 10)
            # A self-hosted manifest cannot authorize different bytes from GitHub.
            rebuilt.unlink()
            with self.assertRaises(ValueError):
                apply_patch(baseline, patch, rebuilt, size, "0" * 64, threading.Event())
            baseline.write_bytes(b"broken baseline")
            with self.assertRaises(ValueError):
                apply_patch(baseline, patch, rebuilt, size, digest, threading.Event())


if __name__ == "__main__":
    unittest.main()

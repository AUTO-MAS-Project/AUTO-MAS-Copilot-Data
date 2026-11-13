"""生成器与字节重建契约；不下载或运行 MaaEnd。"""

import hashlib
import random
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from copilot_data.zip_delta import apply_patch, create_patch, create_bundle
from copilot_data.maaend_delta import select_bases


class MaaEndDeltaTests(unittest.TestCase):
    def test_version_window_and_same_number_beta_anchor(self):
        releases = [
            {"tag_name": "v" + tag}
            for tag in ("2.7.0", "2.8.0", "2.9.0", "3.0.0", "3.1.0")
        ]
        releases += [{"tag_name": "v3.1.0-beta.1", "prerelease": True}]
        self.assertEqual(
            select_bases(releases, "v3.1.0", "stable"), ["v3.0.0", "v2.9.0", "v2.8.0"]
        )
        self.assertEqual(select_bases(releases, "v3.1.0-beta.8", "beta"), ["v3.1.0"])
        self.assertEqual(select_bases(releases, "v3.2.0-beta.8", "beta"), [])
        with self.assertRaises(ValueError):
            select_bases(releases, "v3.1.0-beta.8", "stable")

    def test_three_sources_share_payload_and_each_rebuilds_exact_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = random.Random(27).randbytes(1024 * 1024)
            sources = []
            for number in range(3):
                source = root / f"base-{number}.zip"
                with zipfile.ZipFile(source, "w") as archive:
                    archive.writestr("shared.bin", data)
                    archive.writestr("removed.txt", "delete")
                    if number == 0:
                        archive.writestr("new.txt", "already current")
                sources.append(source)
            target = root / "target.zip"
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("new.txt", "already current")
                archive.writestr("shared.bin", data)
                archive.writestr("added.txt", "new")
            patch = root / "bundle.zip"
            create_bundle(
                sources, target, patch, {"bases": ["3.0.0", "2.9.0", "2.8.0"]}
            )
            self.assertLess(patch.stat().st_size, 8192)
            for number, source in enumerate(sources):
                output = root / f"rebuilt-{number}.zip"
                apply_patch(
                    source,
                    patch,
                    output,
                    target.stat().st_size,
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    threading.Event(),
                )
                self.assertEqual(output.read_bytes(), target.read_bytes())

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

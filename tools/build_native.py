"""Build only local Swift source with the installed Apple toolchain; no downloads."""
import argparse
from pathlib import Path
import plistlib
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--demo", action="store_true", help="Also compile the disposable Cocoa demo app")
args = parser.parse_args()
if sys.platform != "darwin":
    raise SystemExit("macOS is required")
build = root / "build"
build.mkdir(exist_ok=True)
cache = build / "module-cache"
cache.mkdir(exist_ok=True)
targets = [(root / "native/Native.swift", build / "native-helper")]
if args.demo:
    contents = build / "SafeMacDemo.app/Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "org.klara.SafeMacDemo", "CFBundleName": "SafeMacDemo",
        "CFBundleExecutable": "SafeMacDemo", "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1", "NSHighResolutionCapable": True,
    }))
    targets.append((root / "examples/SafeMacDemo.swift", contents / "MacOS/SafeMacDemo"))
for source, target in targets:
    if target.exists():
        raise SystemExit(f"Refusing to overwrite existing binary: {target}")
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-module-cache-path", str(cache),
                    str(source), "-o", str(target)], check=True, timeout=120)
    print(target.relative_to(root))

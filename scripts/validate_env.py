# -*- coding: utf-8 -*-
"""
scripts/validate_env.py -- Quick environment validation.

Run: python scripts/validate_env.py
Checks: Python version, imports, .env, config, DB creation.
"""

import sys
import os
import io
from pathlib import Path

# Force UTF-8 output on Windows terminals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_PYTHON = (3, 10)
ERRORS = []
WARNINGS = []

print("🧬 Mr. ADN — Environment Validator")
print("=" * 45)

# Python version
major, minor = sys.version_info[:2]
if (major, minor) < REQUIRED_PYTHON:
    ERRORS.append(f"Python {major}.{minor} < required {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}")
else:
    print(f"✅ Python {major}.{minor}.{sys.version_info[2]}")

# Core imports
packages = {
    "PyQt6": "PyQt6",
    "google.genai": "google-genai",
    "loguru": "loguru",
    "dotenv": "python-dotenv",
    "pydantic": "pydantic",
}
for module, pkg in packages.items():
    try:
        __import__(module)
        print(f"✅ {pkg}")
    except ImportError:
        ERRORS.append(f"Missing: {pkg} (pip install {pkg})")
        print(f"❌ {pkg}")

# Optional
optional = {
    "win32gui": "pywin32",
    "pynput": "pynput",
    "mss": "mss",
    "PIL": "Pillow",
    "sounddevice": "sounddevice",
}
for module, pkg in optional.items():
    try:
        __import__(module)
        print(f"✅ {pkg} (optional)")
    except ImportError:
        WARNINGS.append(f"Optional missing: {pkg}")
        print(f"⚠️  {pkg} (optional — some features disabled)")

# Config file
cfg_path = ROOT / "config" / "config.json"
if cfg_path.exists():
    print(f"✅ config.json found")
else:
    ERRORS.append("config/config.json missing")
    print("❌ config/config.json missing")

# .env / API key
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
gemini_key = os.getenv("GEMINI_API_KEY", "")
if gemini_key and not gemini_key.startswith("your_"):
    print("✅ GEMINI_API_KEY set")
else:
    WARNINGS.append("GEMINI_API_KEY not set in .env — AI will not work")
    print("⚠️  GEMINI_API_KEY not set in .env")

# DB creation test
try:
    from core.database import DatabaseManager
    test_db_path = ROOT / "data" / "_test_validate.db"
    db = DatabaseManager(test_db_path)
    db.initialize()
    db.close()
    test_db_path.unlink(missing_ok=True)
    print("✅ SQLite DatabaseManager OK")
except Exception as e:
    ERRORS.append(f"DatabaseManager failed: {e}")
    print(f"❌ DatabaseManager: {e}")

# Config manager
try:
    from core.config_manager import ConfigManager
    cfg = ConfigManager()
    assert cfg.get("app.name") == "Mr. ADN"
    print("✅ ConfigManager OK")
except Exception as e:
    ERRORS.append(f"ConfigManager failed: {e}")
    print(f"❌ ConfigManager: {e}")

# Summary
print("\n" + "=" * 45)
if ERRORS:
    print(f"❌ {len(ERRORS)} ERROR(S) — fix before running main.py:")
    for e in ERRORS:
        print(f"   • {e}")
    sys.exit(1)
elif WARNINGS:
    print(f"⚠️  {len(WARNINGS)} warning(s) — optional features may be limited.")
    for w in WARNINGS:
        print(f"   • {w}")
    print("\n✅ Environment is valid. Run: python main.py")
else:
    print("✅ All checks passed. Run: python main.py")

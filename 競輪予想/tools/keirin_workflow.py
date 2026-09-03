#!/usr/bin/env python3
"""競輪予想の検証・記録・Chatwork。6:00は第一予想まで。最終転記はChatGPT最終予想だけ。"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
import keirin_drive_state as drive_state  # noqa: E402
from keirin_submission_state import chatwork_sending_enabled  # noqa: E402

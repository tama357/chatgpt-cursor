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


PICK_RE = re.compile(r"^([1-9])-([1-9])-([1-9]+)$")
TRIFECTA_RE = re.compile(r"^[1-9]-[1-9]-[1-9]$")
ALLOWED_TARGETS = {"鉄板", "中穴", "大穴"}
ALLOWED_CONFIDENCE = {"A", "B", "C"}
ALLOWED_TICKET_TYPES = {"本線", "抑え"}
ALLOWED_STATUS = {"的中", "ハズレ"}
RACE_COUNT = 3
MAX_COMBINATIONS = 10
MIN_CLOSE_TIME = "18:00"
MISS_REASONS = {
    "axis_miss",
    "second_place_miss",
    "third_place_miss",
    "line_collapse",
    "unexpected_position",
    "upset",
    "accident",
    "other",
}

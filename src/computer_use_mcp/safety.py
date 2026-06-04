"""Safety controls beyond the allowlist gate (DESIGN §E):

  - is_dangerous()        keyword check for send/delete/submit/pay-style actions
  - message_box_confirm() human Yes/No via a native MessageBox (in the loop)
  - EStop                 global panic hotkey (default Ctrl+Alt+Q) -> latch off
  - redact()              black out sensitive-window regions in a screenshot
"""
from __future__ import annotations

import ctypes
import io
import threading
import time

# --- dangerous-action detection ---------------------------------------------

DANGEROUS_WORDS = (
    "发送", "删除", "提交", "付款", "支付", "确认", "确定", "购买", "下单", "转账", "卸载",
    "send", "delete", "submit", "pay", "confirm", "remove", "discard", "uninstall", "buy",
)


def is_dangerous(text: str | None, words=DANGEROUS_WORDS) -> bool:
    t = (text or "").lower()
    return any(w.lower() in t for w in words)


# --- human confirmation ------------------------------------------------------

def message_box_confirm(prompt: str) -> bool:
    """Native Yes/No box, topmost+foreground. Blocks until the human answers —
    that blocking IS the safety property. Returns True only on Yes."""
    MB_YESNO, MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST, IDYES = 0x4, 0x30, 0x10000, 0x40000, 6
    res = ctypes.windll.user32.MessageBoxW(
        0, prompt, "computer-use-mcp — 危险动作确认",
        MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST,
    )
    return res == IDYES


# --- e-stop hotkey -----------------------------------------------------------

_VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pause": 0x13,
    "home": 0x24, "end": 0x23, "del": 0x2E, "delete": 0x2E,
}


def _vk(token: str) -> int | None:
    t = token.strip().lower()
    if t in _VK:
        return _VK[t]
    if len(t) == 1 and t.isalnum():
        return ord(t.upper())
    if len(t) >= 2 and t[0] == "f" and t[1:].isdigit() and 1 <= int(t[1:]) <= 24:
        return 0x70 + int(t[1:]) - 1
    return None


def parse_combo(combo: str) -> list[int]:
    return [v for v in (_vk(p) for p in combo.replace(" ", "").split("+") if p) if v is not None]


class EStop:
    """A global panic hotkey. When the combo is held, latches engaged; once
    engaged, the server refuses every action until restarted."""

    def __init__(self, combo: str = "ctrl+alt+q", poll: float = 0.05):
        self.combo = combo
        self.vks = parse_combo(combo)
        self.poll = poll
        self._engaged = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def engaged(self) -> bool:
        return self._engaged.is_set()

    def engage(self) -> None:
        self._engaged.set()

    def start(self) -> None:
        if self._thread is not None or not self.vks:
            return
        self._thread = threading.Thread(target=self._loop, name="estop", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        user32.GetAsyncKeyState.restype = ctypes.c_short
        while not self._engaged.is_set():
            if all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in self.vks):
                self._engaged.set()
                break
            time.sleep(self.poll)


# --- screenshot redaction ----------------------------------------------------

def redact(png_bytes: bytes, regions) -> bytes:
    """Fill the given (x, y, w, h) regions with black in a PNG. Regions are in
    the screenshot's pixel space (same as Window.bounds on the primary monitor)."""
    regions = [r for r in regions if r and r[2] > 0 and r[3] > 0]
    if not regions:
        return png_bytes
    from PIL import Image, ImageDraw

    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(im)
    for x, y, w, h in regions:
        draw.rectangle([x, y, x + w, y + h], fill=(0, 0, 0))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()

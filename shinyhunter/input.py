from __future__ import annotations

import socket
import struct
import time


INPUT_PORT = 4950
HID_NEUTRAL = 0x00000FFF
TOUCH_NEUTRAL = 0x02000000
CPAD_NEUTRAL = 0x007FF7FF
NEW3DS_NEUTRAL = 0x80800081
INTERFACE_BUTTONS = 0x00000000

BUTTONS = {
    "A": 0,
    "B": 1,
    "SELECT": 2,
    "START": 3,
    "RIGHT": 4,
    "LEFT": 5,
    "UP": 6,
    "DOWN": 7,
    "R": 8,
    "L": 9,
    "X": 10,
    "Y": 11,
}


class InputError(RuntimeError):
    pass


class InputRedirection:
    def __init__(self, ip: str, port: int = INPUT_PORT, interval: float = 0.005):
        self.address = (ip, port)
        self.interval = interval
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.held: set[str] = set()

    def close(self) -> None:
        try:
            self.release_all()
        finally:
            self.sock.close()

    def _hid(self) -> int:
        hid = HID_NEUTRAL
        for button in self.held:
            try:
                bit = BUTTONS[button]
            except KeyError as exc:
                raise InputError(f"Unknown button: {button}") from exc
            hid &= ~(1 << bit)
        return hid

    def _packet(self) -> bytes:
        return struct.pack(
            "<IIIII",
            self._hid(),
            TOUCH_NEUTRAL,
            CPAD_NEUTRAL,
            NEW3DS_NEUTRAL,
            INTERFACE_BUTTONS,
        )

    def pump(self, seconds: float) -> None:
        end = time.monotonic() + max(0.0, seconds)
        packet = self._packet()
        while time.monotonic() < end:
            self.sock.sendto(packet, self.address)
            time.sleep(self.interval)

    def hold(self, *buttons: str) -> None:
        for button in buttons:
            button = button.upper()
            if button not in BUTTONS:
                raise InputError(f"Unknown button: {button}")
            self.held.add(button)
        # Push new state immediately.
        self.sock.sendto(self._packet(), self.address)

    def release(self, *buttons: str) -> None:
        for button in buttons:
            self.held.discard(button.upper())
        self.sock.sendto(self._packet(), self.address)

    def release_all(self) -> None:
        self.held.clear()
        try:
            self.pump(0.03)
        except OSError:
            pass

    def press(self, buttons: list[str], duration: float = 0.10, after: float = 0.05) -> None:
        old = set(self.held)
        try:
            self.hold(*buttons)
            self.pump(duration)
        finally:
            self.held = old
            self.pump(after)

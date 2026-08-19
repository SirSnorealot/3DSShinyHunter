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
SPECIAL_HOME = 1 << 0
SPECIAL_POWER = 1 << 1
SPECIAL_POWER_LONG = 1 << 2

# Luma InputRedirection is UDP and has no acknowledgement.  Keep transitions
# on a conservative cadence and repeat them so a single lost datagram does not
# turn into a missed or stuck button press.
DEFAULT_PACKET_INTERVAL = 0.010
DEFAULT_PRESS_DURATION = 0.180
DEFAULT_RELEASE_DURATION = 0.150
TRANSITION_REPEATS = 3
HOME_PRE_NEUTRAL = 0.100
HOME_PRESS_DURATION = 0.250
HOME_RELEASE_DURATION = 0.300

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
    def __init__(
        self,
        ip: str,
        port: int = INPUT_PORT,
        interval: float = DEFAULT_PACKET_INTERVAL,
    ):
        self.address = (ip, port)
        self.interval = max(0.001, interval)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.held: set[str] = set()
        self.special_buttons = 0

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
            self.special_buttons,
        )

    def _send_transition(self, repeats: int = TRANSITION_REPEATS) -> None:
        """Repeat the current state to make an edge resilient to UDP loss."""
        packet = self._packet()
        for index in range(max(1, repeats)):
            self.sock.sendto(packet, self.address)
            if index + 1 < repeats:
                time.sleep(self.interval)

    def pump(self, seconds: float) -> None:
        """Continuously transmit the current controller state for *seconds*."""
        seconds = max(0.0, seconds)
        packet = self._packet()
        if seconds == 0.0:
            self.sock.sendto(packet, self.address)
            return

        end = time.monotonic() + seconds
        while True:
            self.sock.sendto(packet, self.address)
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.interval, remaining))

    def wait(self, seconds: float) -> float:
        """Wait, continuing to publish state only while something is held."""
        seconds = max(0.0, seconds)
        start = time.monotonic()
        if self.held or self.special_buttons:
            self.pump(seconds)
        else:
            time.sleep(seconds)
        return time.monotonic() - start

    def _validate_buttons(self, buttons: tuple[str, ...] | list[str]) -> list[str]:
        normalized = [button.upper() for button in buttons]
        for button in normalized:
            if button not in BUTTONS:
                raise InputError(f"Unknown button: {button}")
        return normalized

    def hold(self, *buttons: str) -> None:
        for button in self._validate_buttons(buttons):
            self.held.add(button)
        self._send_transition()

    def release(self, *buttons: str) -> None:
        for button in self._validate_buttons(buttons):
            self.held.discard(button)
        self._send_transition()
        # Keep publishing the released state briefly; losing the release edge
        # is worse than losing a press because it can leave a button stuck.
        self.pump(DEFAULT_RELEASE_DURATION)

    def release_all(self) -> None:
        self.held.clear()
        self.special_buttons = 0
        try:
            self._send_transition(repeats=5)
            self.pump(DEFAULT_RELEASE_DURATION)
        except OSError:
            pass

    def press_home(
        self,
        duration: float = HOME_PRESS_DURATION,
        after: float = HOME_RELEASE_DURATION,
    ) -> None:
        """Reliably press HOME using Luma's special-button bit 0.

        HOME is edge-driven.  Publish a clean released state first, then a
        sustained pressed state, then a sustained release so packet loss at a
        single transition cannot erase the HOME event.
        """
        old = self.special_buttons
        try:
            self.special_buttons = old & ~SPECIAL_HOME
            self._send_transition(repeats=5)
            self.pump(HOME_PRE_NEUTRAL)

            self.special_buttons = old | SPECIAL_HOME
            self._send_transition(repeats=5)
            self.pump(max(0.0, duration))
        finally:
            self.special_buttons = old & ~SPECIAL_HOME
            self._send_transition(repeats=5)
            self.pump(max(0.0, after))

    def press(
        self,
        buttons: list[str],
        duration: float = DEFAULT_PRESS_DURATION,
        after: float = DEFAULT_RELEASE_DURATION,
    ) -> None:
        buttons = self._validate_buttons(buttons)
        old = set(self.held)
        try:
            # Reassert the pre-press state first.  This creates a clean edge
            # even if the previous release packet was lost.
            self._send_transition()

            self.held.update(buttons)
            self._send_transition()
            self.pump(max(0.0, duration))
        finally:
            self.held = old
            self._send_transition(repeats=5)
            self.pump(max(DEFAULT_RELEASE_DURATION, after))

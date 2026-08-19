from __future__ import annotations

import random
import socket
import struct
import time


MAGIC = b"SH3D"
VERSION = 1
CMD_PING = 1
CMD_READ = 2
STATUS_OK = 0

_REQUEST = struct.Struct("<4sBBHIII")
_RESPONSE = struct.Struct("<4sBBHII")


class PluginError(RuntimeError):
    pass


class PluginMemoryClient:
    """UDP client for the 3DSShinyHunter 3GX memory bridge."""

    def __init__(self, host: str, port: int = 4951, timeout: float = 1.0, retries: int = 3):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    def close(self) -> None:
        self.sock.close()

    def _exchange(self, command: int, address: int = 0, size: int = 0) -> bytes:
        request_id = random.getrandbits(32)
        request = _REQUEST.pack(
            MAGIC,
            VERSION,
            command,
            0,
            request_id,
            address & 0xFFFFFFFF,
            size & 0xFFFFFFFF,
        )

        last_error: Exception | None = None
        for _ in range(self.retries):
            try:
                self.sock.sendto(request, (self.host, self.port))
                while True:
                    packet, peer = self.sock.recvfrom(2048)
                    if peer[0] != self.host or len(packet) < _RESPONSE.size:
                        continue
                    magic, version, status, _reserved, reply_id, payload_size = _RESPONSE.unpack_from(packet)
                    if magic != MAGIC or version != VERSION or reply_id != request_id:
                        continue
                    payload = packet[_RESPONSE.size:]
                    if len(payload) != payload_size:
                        raise PluginError(
                            f"Plugin response size mismatch: header={payload_size} actual={len(payload)}"
                        )
                    if status != STATUS_OK:
                        detail = payload.decode("utf-8", errors="replace") if payload else "no detail"
                        raise PluginError(f"Plugin status {status}: {detail}")
                    return payload
            except (socket.timeout, OSError, PluginError) as exc:
                last_error = exc

        raise PluginError(
            f"No valid reply from 3GX plugin at {self.host}:{self.port}: {last_error}"
        )

    def ping(self) -> str:
        payload = self._exchange(CMD_PING)
        return payload.decode("ascii", errors="replace")

    def read_memory(self, address: int, size: int) -> bytes:
        if not 0 < size <= 512:
            raise ValueError("Plugin read size must be 1..512 bytes")
        payload = self._exchange(CMD_READ, address, size)
        if len(payload) != size:
            raise PluginError(f"Plugin returned {len(payload)} bytes, expected {size}")
        return payload

    def wait_ready(self, timeout: float = 30.0, poll_interval: float = 0.25) -> str:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.ping()
            except (OSError, PluginError) as exc:
                last_error = exc
                time.sleep(poll_interval)
        raise PluginError(
            f"Timed out after {timeout:.1f}s waiting for 3GX plugin"
            + (f"; last error: {last_error}" if last_error else "")
        )
    def wait_gone(self, timeout: float = 10.0, poll_interval: float = 0.20) -> None:
        """Wait until the current game/plugin instance stops answering.

        This intentionally uses short, single-shot probes so process teardown
        is detected quickly instead of spending the normal retry budget on a
        plugin that is expected to disappear.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.settimeout(min(0.25, max(0.05, deadline - time.monotonic())))
            try:
                request_id = random.getrandbits(32)
                request = _REQUEST.pack(MAGIC, VERSION, CMD_PING, 0, request_id, 0, 0)
                probe.sendto(request, (self.host, self.port))
                try:
                    packet, peer = probe.recvfrom(2048)
                except socket.timeout:
                    return
                if peer[0] != self.host or len(packet) < _RESPONSE.size:
                    return
                magic, version, _status, _reserved, reply_id, _payload_size = _RESPONSE.unpack_from(packet)
                if magic != MAGIC or version != VERSION or reply_id != request_id:
                    return
            except OSError:
                return
            finally:
                probe.close()
            time.sleep(poll_interval)
        raise PluginError(
            f"Timed out after {timeout:.1f}s waiting for old 3GX plugin instance to stop"
        )


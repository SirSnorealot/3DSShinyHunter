from __future__ import annotations

import socket
import time
import xml.etree.ElementTree as ET


class RSPError(RuntimeError):
    pass


def _checksum(payload: bytes) -> int:
    return sum(payload) & 0xFF


def _packet(payload: str | bytes) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("ascii")
    return b"$" + payload + b"#" + f"{_checksum(payload):02x}".encode("ascii")


class LumaRSP:
    """Small GDB-RSP client for Luma3DS."""

    def __init__(self, ip: str, port: int = 4000, timeout: float = 3.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.attached_pid: int | None = None
        self.running = False

    def connect(self) -> None:
        self.sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

        supported = self.command("qSupported:multiprocess+;xmlRegisters=i386")
        if b"multiprocess+" not in supported:
            raise RSPError(f"Unexpected Luma GDB capabilities: {supported!r}")

        ext = self.command("!")
        if ext != b"OK":
            raise RSPError(f"Could not enter extended-remote mode: {ext!r}")

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _recv_byte(self) -> bytes:
        if self.sock is None:
            raise RSPError("Not connected")
        data = self.sock.recv(1)
        if not data:
            raise RSPError("GDB connection closed")
        return data

    def recv_packet(self) -> bytes:
        if self.sock is None:
            raise RSPError("Not connected")

        while True:
            b = self._recv_byte()
            if b in (b"+", b"-"):
                continue
            if b == b"$":
                break

        encoded = bytearray()
        while True:
            b = self._recv_byte()
            if b == b"#":
                break
            encoded += b

        recv_sum = self.sock.recv(2)
        try:
            expected = int(recv_sum.decode("ascii"), 16)
        except ValueError:
            expected = -1

        actual = _checksum(bytes(encoded))
        if actual != expected:
            try:
                self.sock.sendall(b"-")
            except OSError:
                pass
            raise RSPError(
                f"Bad RSP checksum: expected {expected:02x}, calculated {actual:02x}"
            )

        try:
            self.sock.sendall(b"+")
        except OSError:
            pass

        # Standard RSP unescaping + run-length decoding.
        raw = bytes(encoded)
        out = bytearray()
        i = 0
        while i < len(raw):
            c = raw[i]
            if c == 0x7D and i + 1 < len(raw):  # }
                out.append(raw[i + 1] ^ 0x20)
                i += 2
            elif c == 0x2A and out and i + 1 < len(raw):  # *
                count = raw[i + 1] - 29
                if count > 0:
                    out.extend([out[-1]] * count)
                i += 2
            else:
                out.append(c)
                i += 1
        return bytes(out)

    def command(self, payload: str | bytes) -> bytes:
        if self.sock is None:
            raise RSPError("Not connected")
        self.sock.sendall(_packet(payload))
        return self.recv_packet()

    def qxfer(self, obj: str, annex: str, chunk_size: int = 0x300) -> bytes:
        offset = 0
        result = bytearray()

        while True:
            reply = self.command(
                f"qXfer:{obj}:read:{annex}:{offset:x},{chunk_size:x}"
            )
            if not reply or reply[:1] not in (b"m", b"l"):
                raise RSPError(f"Unexpected qXfer reply: {reply[:200]!r}")

            result.extend(reply[1:])
            offset += len(reply) - 1
            if reply[:1] == b"l":
                return bytes(result)

    def processes(self) -> list[dict[str, str]]:
        xml = self.qxfer("osdata", "processes")
        root = ET.fromstring(xml)
        rows: list[dict[str, str]] = []

        for item in root.findall(".//item"):
            row: dict[str, str] = {}
            for col in item.findall("./column"):
                name = col.attrib.get("name", "").strip().lower()
                if name:
                    row[name] = (col.text or "").strip()
            if row:
                rows.append(row)
        return rows

    @staticmethod
    def _row_pid(row: dict[str, str]) -> int | None:
        for key in ("pid", "process-id", "processid", "id"):
            if key in row:
                value = row[key]
                try:
                    return int(value, 16) if value.lower().startswith("0x") else int(value)
                except ValueError:
                    pass
        return None

    def find_process(self, name: str, configured_pid: int | None = None) -> int:
        rows = self.processes()

        if configured_pid is not None:
            pids = {self._row_pid(r) for r in rows}
            if configured_pid not in pids:
                raise RSPError(f"Configured PID {configured_pid} is not running")
            return configured_pid

        target = name.casefold()
        matches = []
        for row in rows:
            text = " ".join(row.values()).casefold()
            pid = self._row_pid(row)
            if pid is not None and target in text:
                matches.append((pid, row))

        if not matches:
            visible = ", ".join(
                f"{self._row_pid(r)}:{r.get('command', r.get('name', '?'))}"
                for r in rows
            )
            raise RSPError(f"Process {name!r} not found. Running: {visible}")

        return matches[0][0]

    def attach(self, pid: int) -> bytes:
        reply = self.command(f"vAttach;{pid:x}")
        if reply.startswith(b"E"):
            raise RSPError(f"Attach to PID {pid} failed: {reply!r}")
        self.attached_pid = pid
        self.running = False
        return reply

    def interrupt(self) -> bytes:
        if self.sock is None:
            raise RSPError("Not connected")
        if not self.running:
            return b"already-stopped"

        # GDB interrupt is a raw 0x03 byte, not an RSP packet.
        self.sock.sendall(b"\x03")
        reply = self.recv_packet()
        if reply.startswith(b"E"):
            raise RSPError(f"Interrupt failed: {reply!r}")
        self.running = False
        return reply

    def resume(self) -> None:
        if self.sock is None:
            raise RSPError("Not connected")
        if self.running:
            return
        self.sock.sendall(_packet("vCont;c"))
        # Do not wait: reply is asynchronous when target stops later.
        self.running = True

    def read_memory_stopped(self, address: int, size: int) -> bytes:
        if self.running:
            raise RSPError("Target must be stopped before memory reads")

        out = bytearray()
        pos = 0
        while pos < size:
            count = min(0x180, size - pos)
            reply = self.command(f"m{address + pos:x},{count:x}")
            if reply.startswith(b"E"):
                raise RSPError(
                    f"Memory read failed at 0x{address + pos:08X}: {reply!r}"
                )
            try:
                chunk = bytes.fromhex(reply.decode("ascii"))
            except ValueError as exc:
                raise RSPError(f"Invalid memory response: {reply[:80]!r}") from exc
            if len(chunk) != count:
                raise RSPError(
                    f"Short memory read at 0x{address + pos:08X}: "
                    f"{len(chunk)}/{count}"
                )
            out.extend(chunk)
            pos += count
        return bytes(out)

    def read_memory(self, address: int, size: int) -> bytes:
        """Interrupt if needed, read RAM, then restore prior running state."""
        was_running = self.running
        if was_running:
            self.interrupt()

        try:
            return self.read_memory_stopped(address, size)
        finally:
            if was_running:
                self.resume()

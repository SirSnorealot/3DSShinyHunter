from __future__ import annotations

import socket
import time
import xml.etree.ElementTree as ET


class RSPError(RuntimeError):
    pass


class TargetExited(RSPError):
    """The process currently attached to GDB exited or was terminated."""

    def __init__(self, reply: bytes, where: str = ""):
        self.reply = reply
        self.where = where
        prefix = f"Target exited {where}: " if where else "Target exited: "
        super().__init__(prefix + repr(reply))


def _checksum(payload: bytes) -> int:
    return sum(payload) & 0xFF


def _packet(payload: str | bytes) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("ascii")
    return b"$" + payload + b"#" + f"{_checksum(payload):02x}".encode("ascii")


def _is_stop_reply(reply: bytes) -> bool:
    """Return True for GDB stop notifications (Sxx / Txx)."""
    return len(reply) >= 3 and reply[:1] in (b"S", b"T")


def _is_exit_reply(reply: bytes) -> bool:
    """Return True when the debugged process exited (Wxx / Xxx)."""
    return len(reply) >= 3 and reply[:1] in (b"W", b"X")


class LumaRSP:
    """Small GDB-RSP client for Luma3DS."""

    def __init__(self, ip: str, port: int = 4000, timeout: float = 3.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.attached_pid: int | None = None
        self.running = False
        self.target_name: str | None = None
        self.target_configured_pid: int | None = None
        self.recovery_timeout = 30.0
        self.recovery_poll_interval = 0.25

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
        self.attached_pid = None
        self.running = False

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
        self.target_name = name
        self.target_configured_pid = configured_pid
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

    def detach(self) -> bytes:
        """Detach GDB from the current process and let it continue running.

        The GDB remote protocol supports D;pid in multiprocess mode. Detaching
        before a title soft reset avoids carrying debugger state into process
        teardown/relaunch.
        """
        if self.sock is None:
            raise RSPError("Not connected")
        if self.attached_pid is None:
            return b"not-attached"

        pid = self.attached_pid
        reply = self.command(f"D;{pid:x}")
        if reply.startswith(b"E"):
            # Some stubs only accept the non-multiprocess form.
            reply = self.command("D")
        if reply not in (b"OK", b""):
            raise RSPError(f"Detach from PID {pid} failed: {reply!r}")

        self.attached_pid = None
        self.running = False
        return reply

    def reconnect_target(self, timeout: float | None = None, resume: bool = True) -> int:
        """Open a fresh GDB session and attach to the configured target again."""
        if not self.target_name:
            raise RSPError("Cannot reconnect target: process name is unknown")

        timeout = self.recovery_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        self.close()

        while time.monotonic() < deadline:
            try:
                self.connect()
                pid = self.find_process(
                    self.target_name,
                    self.target_configured_pid,
                )
                self.attach(pid)
                if resume:
                    self.resume()
                return pid
            except (OSError, RSPError) as exc:
                last_error = exc
                self.close()
                time.sleep(self.recovery_poll_interval)

        raise RSPError(
            f"Timed out after {timeout:.1f}s waiting for "
            f"process {self.target_name!r} to become attachable"
            + (f"; last error: {last_error}" if last_error else "")
        )

    def configure_target(self, name: str, configured_pid: int | None = None) -> None:
        """Remember which process future short-lived RAM sessions should use."""
        self.target_name = name
        self.target_configured_pid = configured_pid

    def wait_for_target(self, timeout: float = 30.0) -> int:
        """Wait until the configured process is visible, without attaching to it."""
        if not self.target_name:
            raise RSPError("Cannot wait for target: process name is unknown")

        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        self.close()

        while time.monotonic() < deadline:
            try:
                self.connect()
                pid = self.find_process(
                    self.target_name,
                    self.target_configured_pid,
                )
                self.close()
                return pid
            except (OSError, RSPError) as exc:
                last_error = exc
                self.close()
                time.sleep(self.recovery_poll_interval)

        raise RSPError(
            f"Timed out after {timeout:.1f}s waiting for "
            f"process {self.target_name!r}"
            + (f"; last error: {last_error}" if last_error else "")
        )

    def read_memory_ephemeral(
        self,
        address: int,
        size: int,
        *,
        attempts: int = 3,
        retry_delay: float = 0.25,
    ) -> bytes:
        """Read RAM using a short-lived debugger attachment.

        Each call creates a fresh GDB connection, attaches while the game is
        stopped, reads the requested memory, detaches *before the game resumes*,
        and closes the TCP session. This deliberately avoids leaving Pokemon
        under debugger control between hunt actions or across soft resets.
        """
        if not self.target_name:
            raise RSPError("Cannot read memory: target process is not configured")

        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            self.close()
            attached = False
            try:
                self.connect()
                pid = self.find_process(
                    self.target_name,
                    self.target_configured_pid,
                )
                self.attach(pid)
                attached = True

                # vAttach leaves the title stopped, so no interrupt/resume race
                # is needed around the actual read.
                data = self.read_memory_stopped(address, size)

                # Detach while still stopped. The remote D packet releases and
                # continues the process. This is intentionally done immediately
                # after the read instead of seconds later at reset time.
                self.detach()
                attached = False
                self.close()
                return data

            except (OSError, RSPError, TargetExited) as exc:
                last_error = exc

                # If the title is still attached and stopped after an ordinary
                # read error, make one best-effort attempt to let it continue.
                if attached and self.sock is not None:
                    try:
                        self.detach()
                        attached = False
                    except Exception:
                        try:
                            self.resume()
                        except Exception:
                            pass

                self.close()
                if attempt < attempts:
                    time.sleep(retry_delay)
                    continue
                raise RSPError(
                    f"Ephemeral RAM read failed after {attempts} attempts: {last_error}"
                ) from exc

        raise RSPError("Ephemeral RAM read failed")

    def interrupt(self) -> bytes:
        if self.sock is None:
            raise RSPError("Not connected")
        if not self.running:
            return b"already-stopped"

        # GDB interrupt is a raw 0x03 byte, not an RSP packet. Luma answers
        # asynchronously with an Sxx/Txx stop notification. Do not consider
        # the target stopped until that notification has actually arrived.
        self.sock.sendall(b"\x03")

        while True:
            reply = self.recv_packet()

            if _is_stop_reply(reply):
                self.running = False
                return reply

            if _is_exit_reply(reply):
                self.running = False
                self.attached_pid = None
                raise TargetExited(reply, "while interrupting")

            if reply.startswith(b"E"):
                raise RSPError(f"Interrupt failed: {reply!r}")

            # Ignore unrelated asynchronous packets and continue waiting for
            # the stop acknowledgement corresponding to Ctrl+C.

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
        if self.sock is None:
            raise RSPError("Not connected")

        out = bytearray()
        pos = 0
        while pos < size:
            count = min(0x180, size - pos)
            request_address = address + pos

            # Do not use command() here. Stop notifications are asynchronous
            # in GDB RSP and can legally arrive before the actual response to
            # this memory request. We must consume them rather than trying to
            # interpret e.g. b'S02' as hexadecimal RAM bytes.
            self.sock.sendall(_packet(f"m{request_address:x},{count:x}"))

            while True:
                reply = self.recv_packet()

                if _is_stop_reply(reply):
                    # The process is stopped, which is exactly the state RAM
                    # reads require. Continue waiting for the m-packet reply.
                    self.running = False
                    continue

                if _is_exit_reply(reply):
                    self.running = False
                    self.attached_pid = None
                    raise TargetExited(
                        reply,
                        f"during memory read at 0x{request_address:08X}",
                    )

                if reply.startswith(b"E"):
                    raise RSPError(
                        f"Memory read failed at 0x{request_address:08X}: "
                        f"{reply!r}"
                    )

                try:
                    chunk = bytes.fromhex(reply.decode("ascii"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise RSPError(
                        f"Invalid memory response at 0x{request_address:08X}: "
                        f"{reply[:80]!r}"
                    ) from exc

                if len(chunk) != count:
                    raise RSPError(
                        f"Short memory read at 0x{request_address:08X}: "
                        f"{len(chunk)}/{count}"
                    )

                out.extend(chunk)
                pos += count
                break

        return bytes(out)

    def recover_target(self, timeout: float | None = None) -> int:
        """Recover after an unexpected target exit and leave it stopped."""
        return self.reconnect_target(timeout=timeout, resume=False)

    def read_memory(self, address: int, size: int) -> bytes:
        """Read RAM, automatically recovering if the game restarted.

        Pokémon soft resets terminate the old process. If a Wxx/Xxx packet is
        observed while preparing the RAM read, reconnect to Luma, rediscover
        the configured process by name, attach to the new PID, and retry once.
        """
        for attempt in range(2):
            was_running = self.running
            recovering = False

            try:
                if was_running:
                    self.interrupt()

                data = self.read_memory_stopped(address, size)

                # RAM reads should be transparent to the hunt.
                if not self.running:
                    self.resume()
                return data

            except TargetExited:
                if attempt >= 1:
                    raise

                # The process died between hunt actions. Wait for the title to
                # come back, attach to its new PID, then retry the same read.
                recovering = True
                self.recover_target()
                # Keep the freshly attached process stopped. The next loop
                # iteration can read RAM immediately, then resume it once.
                continue

            finally:
                # On ordinary errors, do not intentionally leave a live title
                # paused. During restart recovery, however, deliberately keep
                # the fresh attachment stopped until the retry reads RAM.
                if (
                    not recovering
                    and self.attached_pid is not None
                    and not self.running
                ):
                    try:
                        self.resume()
                    except (OSError, RSPError):
                        pass

        raise RSPError("Memory read recovery failed")

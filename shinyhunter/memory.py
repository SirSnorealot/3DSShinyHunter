from __future__ import annotations


class GDBMemoryBackend:
    label = "GDB"
    kind = "gdb"

    def __init__(self, rsp):
        self.rsp = rsp

    def read_memory(self, address: int, size: int) -> bytes:
        return self.rsp.read_memory_ephemeral(address, size)

    def wait_ready(self, timeout: float = 30.0):
        return self.rsp.wait_for_target(timeout=timeout)

    def before_restart(self) -> None:
        self.rsp.close()

    def wait_stopped(self, timeout: float = 10.0) -> None:
        # GDB restart path does not currently require an explicit offline probe.
        return None

    def close(self) -> None:
        self.rsp.close()


class PluginMemoryBackend:
    label = "PLUGIN"
    kind = "plugin"

    def __init__(self, client):
        self.client = client

    def read_memory(self, address: int, size: int) -> bytes:
        return self.client.read_memory(address, size)

    def wait_ready(self, timeout: float = 30.0):
        return self.client.wait_ready(timeout=timeout)

    def before_restart(self) -> None:
        # UDP is stateless. The same PC client can talk to a newly launched
        # plugin instance after the old title process has been closed.
        pass

    def wait_stopped(self, timeout: float = 10.0) -> None:
        self.client.wait_gone(timeout=timeout)

    def close(self) -> None:
        self.client.close()

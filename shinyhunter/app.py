from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .context import HuntContext
from .dsl import ScriptError, HuntRunner, parse_script
from .input import InputRedirection
from .profile import GameProfile
from .rsp import LumaRSP, RSPError
from .plugin import PluginMemoryClient, PluginError
from .memory import GDBMemoryBackend, PluginMemoryBackend


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Luma3DS RAM + InputRedirection Pokémon hunt runner"
    )
    parser.add_argument("ip", help="3DS IPv4 address")
    parser.add_argument("game", help="Game profile JSON")
    parser.add_argument("hunt", help="Hunt .hunt file")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--memory-backend",
        choices=("gdb", "plugin"),
        help="Override the game profile memory backend",
    )
    parser.add_argument(
        "--log-file",
        help="Append hunt log messages to this text file",
    )
    parser.add_argument(
        "--trace-timing",
        action="store_true",
        help="Print requested and actual elapsed time for each delay",
    )
    args = parser.parse_args(argv)

    profile = GameProfile.load(args.game)
    input_client = InputRedirection(args.ip, profile.input_port)
    backend_name = args.memory_backend or profile.memory_backend
    memory = None

    try:
        print(f"[+] Game: {profile.name}")
        if backend_name == "plugin":
            plugin = PluginMemoryClient(args.ip, profile.plugin_port)
            memory = PluginMemoryBackend(plugin)
            print(f"[+] 3GX memory plugin target: {args.ip}:{profile.plugin_port}")
            hello = memory.wait_ready(timeout=10.0)
            print(f"[+] 3GX plugin ready: {hello}")
        else:
            rsp = LumaRSP(args.ip, profile.gdb_port)
            rsp.configure_target(profile.process_name, profile.process_id)
            memory = GDBMemoryBackend(rsp)
            print("[+] GDB RAM mode: ephemeral (attach only during memory reads)")
            print(f"[+] Checking for process {profile.process_name!r}")
            pid = memory.wait_ready(timeout=10.0)
            print(f"[+] Process {profile.process_name!r}: PID {pid}")
            print("[+] Debugger detached; game left running normally")

        print(f"[+] Memory backend: {backend_name}")
        print(f"[+] InputRedirection target: {args.ip}:{profile.input_port}")

        script_text = Path(args.hunt).read_text(encoding="utf-8")
        nodes = parse_script(script_text)

        ctx = HuntContext(
            profile,
            memory,
            input_client,
            verbose=not args.quiet,
            log_file=args.log_file,
            trace_timing=args.trace_timing,
        )
        print(f"[+] Running hunt: {args.hunt}")
        HuntRunner(ctx).run(nodes)
        print("[+] Hunt finished")
        return 0

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        return 130
    except (OSError, RSPError, PluginError, ScriptError, RuntimeError, ValueError) as exc:
        print(f"\n[ERROR] {exc}")
        return 1
    finally:
        try:
            input_client.release_all()
        except Exception:
            pass
        input_client.close()
        if memory is not None:
            memory.close()


if __name__ == "__main__":
    raise SystemExit(main())

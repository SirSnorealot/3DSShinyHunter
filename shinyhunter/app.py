from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .context import HuntContext
from .dsl import ScriptError, HuntRunner, parse_script
from .input import InputRedirection
from .profile import GameProfile
from .rsp import LumaRSP, RSPError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Luma3DS RAM + InputRedirection Pokémon hunt runner"
    )
    parser.add_argument("ip", help="3DS IPv4 address")
    parser.add_argument("game", help="Game profile JSON")
    parser.add_argument("hunt", help="Hunt .hunt file")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    profile = GameProfile.load(args.game)
    rsp = LumaRSP(args.ip, profile.gdb_port)
    input_client = InputRedirection(args.ip, profile.input_port)

    try:
        print(f"[+] Game: {profile.name}")
        print(f"[+] Connecting GDB {args.ip}:{profile.gdb_port}")
        rsp.connect()

        pid = rsp.find_process(profile.process_name, profile.process_id)
        print(f"[+] Process {profile.process_name!r}: PID {pid}")
        reply = rsp.attach(pid)
        print(f"[+] Attached: {reply[:32]!r}...")

        # Attach stops the title. Scripts should operate against a running game;
        # memory checks will interrupt/resume transparently.
        rsp.resume()
        print("[+] Game resumed")
        print(f"[+] InputRedirection target: {args.ip}:{profile.input_port}")

        script_text = Path(args.hunt).read_text(encoding="utf-8")
        nodes = parse_script(script_text)

        ctx = HuntContext(profile, rsp, input_client, verbose=not args.quiet)
        print(f"[+] Running hunt: {args.hunt}")
        HuntRunner(ctx).run(nodes)
        print("[+] Hunt finished")
        return 0

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        return 130
    except (OSError, RSPError, ScriptError, RuntimeError, ValueError) as exc:
        print(f"\n[ERROR] {exc}")
        return 1
    finally:
        try:
            input_client.release_all()
        except Exception:
            pass
        try:
            if rsp.attached_pid is not None and not rsp.running:
                rsp.resume()
        except Exception:
            pass
        input_client.close()
        rsp.close()


if __name__ == "__main__":
    raise SystemExit(main())

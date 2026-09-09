#!/usr/bin/python3
"""Drive dailyfold on a private Xvfb display.

The session is persistent across invocations. Input commands send native X11
events with xdotool and then capture the GTK window to .ui-harness/latest.png.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".ui-harness"
SESSION_PATH = RUNTIME / "session.json"
LATEST_SHOT = RUNTIME / "latest.png"
SCREEN_SIZE = "1024x768x24"


class UiError(RuntimeError):
    pass


def require_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise UiError(f"missing command: {name}")
    return path


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def load_session(require_live: bool = True) -> dict:
    if not SESSION_PATH.exists():
        raise UiError("UI session is not running; use: scripts/ui.py start")
    try:
        session = json.loads(SESSION_PATH.read_text())
    except (OSError, ValueError) as exc:
        raise UiError(f"cannot read {SESSION_PATH}: {exc}") from exc
    if require_live and not process_alive(session["app_pid"]):
        raise UiError(
            f"dailyfold process {session['app_pid']} exited; see "
            f"{RUNTIME / 'app.log'}"
        )
    if require_live and not process_alive(session["xvfb_pid"]):
        raise UiError(
            f"Xvfb process {session['xvfb_pid']} exited; see "
            f"{RUNTIME / 'xvfb.log'}"
        )
    return session


def xenv(session: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = session["display"]
    env["GDK_BACKEND"] = "x11"
    return env


def xdotool(session: dict, *args: object, check: bool = True) -> subprocess.CompletedProcess:
    command = [require_command("xdotool"), *(str(arg) for arg in args)]
    return subprocess.run(
        command,
        cwd=ROOT,
        env=xenv(session),
        check=check,
        text=True,
        capture_output=True,
    )


def choose_display() -> tuple[str, Path]:
    requested = os.environ.get("DAILYFOLD_UI_DISPLAY")
    numbers = [int(requested.lstrip(":"))] if requested else range(99, 120)
    for number in numbers:
        socket_path = Path(f"/tmp/.X11-unix/X{number}")
        if not socket_path.exists():
            return f":{number}", socket_path
    raise UiError("no free X display found in :99 through :119")


def wait_for(predicate, description: str, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise UiError(f"timed out waiting for {description}")


def start(_args) -> None:
    if SESSION_PATH.exists():
        session = load_session(require_live=False)
        if process_alive(session["app_pid"]) and process_alive(session["xvfb_pid"]):
            print(
                f"already running: display={session['display']} "
                f"window={session['window_id']} app_pid={session['app_pid']}"
            )
            return
        terminate(session["app_pid"], "app.py")
        terminate(session["xvfb_pid"], "Xvfb")
        SESSION_PATH.unlink(missing_ok=True)

    require_command("Xvfb")
    require_command("xdotool")
    if not Path("/usr/bin/python3").exists():
        raise UiError("missing /usr/bin/python3 with GTK bindings")

    RUNTIME.mkdir(parents=True, exist_ok=True)
    display, socket_path = choose_display()
    xvfb_log = (RUNTIME / "xvfb.log").open("wb")
    app_log = (RUNTIME / "app.log").open("wb")
    xvfb = subprocess.Popen(
        [
            require_command("Xvfb"),
            display,
            "-screen",
            "0",
            SCREEN_SIZE,
            "-nolisten",
            "tcp",
            "-ac",
        ],
        cwd=ROOT,
        stdout=xvfb_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        wait_for(lambda: socket_path.exists(), f"X display {display}")
        provisional = {"display": display}
        app_env = xenv(provisional)
        app = subprocess.Popen(
            ["/usr/bin/python3", str(ROOT / "app.py")],
            cwd=ROOT,
            env=app_env,
            stdout=app_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        def find_window():
            if app.poll() is not None:
                raise UiError(
                    f"dailyfold exited with status {app.returncode}; see "
                    f"{RUNTIME / 'app.log'}"
                )
            found = xdotool(
                provisional,
                "search",
                "--onlyvisible",
                "--pid",
                app.pid,
                "--name",
                "^dailyfold$",
                check=False,
            )
            windows = found.stdout.split()
            return windows[0] if windows else None

        window_id = wait_for(find_window, "dailyfold window")
        session = {
            "display": display,
            "window_id": window_id,
            "app_pid": app.pid,
            "xvfb_pid": xvfb.pid,
        }
        SESSION_PATH.write_text(json.dumps(session, indent=2) + "\n")
        focus(session)
        screenshot(session, LATEST_SHOT)
    except Exception:
        if "app" in locals() and app.poll() is None:
            os.killpg(app.pid, signal.SIGTERM)
        if xvfb.poll() is None:
            os.killpg(xvfb.pid, signal.SIGTERM)
        raise
    finally:
        xvfb_log.close()
        app_log.close()

    print(
        f"started: display={display} window={window_id} app_pid={app.pid}\n"
        f"screenshot: {LATEST_SHOT}"
    )


def focus(session: dict) -> None:
    # windowactivate requires a window manager; windowfocus works directly on
    # the bare Xvfb display used by this harness.
    xdotool(session, "windowraise", session["window_id"])
    xdotool(session, "windowfocus", "--sync", session["window_id"])


def geometry(session: dict) -> dict[str, int]:
    result = xdotool(
        session, "getwindowgeometry", "--shell", session["window_id"]
    )
    values = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"X", "Y", "WIDTH", "HEIGHT"}:
            values[key] = int(value)
    if set(values) != {"X", "Y", "WIDTH", "HEIGHT"}:
        raise UiError(f"unexpected window geometry: {result.stdout!r}")
    return values


def screenshot(session: dict, path: Path) -> None:
    # Import GDK only after DISPLAY has been selected for this short-lived CLI
    # process. Capturing the root at the window geometry works without a window
    # manager and includes TextView overlays as the user sees them.
    os.environ.update(xenv(session))
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
    except ImportError as exc:
        raise UiError(
            "GTK Python bindings are unavailable; run this script with "
            "/usr/bin/python3"
        ) from exc

    Gdk.init([])
    root = Gdk.get_default_root_window()
    if root is None:
        raise UiError(f"cannot open X display {session['display']}")
    area = geometry(session)
    pixbuf = Gdk.pixbuf_get_from_window(
        root, area["X"], area["Y"], area["WIDTH"], area["HEIGHT"]
    )
    if pixbuf is None:
        raise UiError("GDK could not capture the dailyfold window")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(path), "png", [], [])


def capture_after_input(session: dict) -> None:
    time.sleep(0.15)
    screenshot(session, LATEST_SHOT)
    print(f"screenshot: {LATEST_SHOT}")


def click(args) -> None:
    session = load_session()
    focus(session)
    xdotool(
        session,
        "mousemove",
        "--sync",
        "--window",
        session["window_id"],
        args.x,
        args.y,
        "click",
        args.button,
    )
    capture_after_input(session)


def move(args) -> None:
    session = load_session()
    xdotool(
        session,
        "mousemove",
        "--sync",
        "--window",
        session["window_id"],
        args.x,
        args.y,
    )
    capture_after_input(session)


def drag(args) -> None:
    session = load_session()
    focus(session)
    xdotool(
        session,
        "mousemove",
        "--sync",
        "--window",
        session["window_id"],
        args.x1,
        args.y1,
        "mousedown",
        args.button,
        "mousemove",
        "--sync",
        "--window",
        session["window_id"],
        args.x2,
        args.y2,
        "mouseup",
        args.button,
    )
    capture_after_input(session)


def type_text(args) -> None:
    session = load_session()
    focus(session)
    xdotool(
        session,
        "type",
        "--window",
        session["window_id"],
        "--clearmodifiers",
        "--delay",
        args.delay,
        args.text,
    )
    capture_after_input(session)


def key(args) -> None:
    session = load_session()
    focus(session)
    xdotool(
        session,
        "key",
        "--window",
        session["window_id"],
        "--clearmodifiers",
        *args.keys,
    )
    capture_after_input(session)


def shot(args) -> None:
    session = load_session()
    path = Path(args.path) if args.path else LATEST_SHOT
    screenshot(session, path)
    print(f"screenshot: {path.resolve()}")


def status(_args) -> None:
    session = load_session()
    area = geometry(session)
    print(
        json.dumps(
            {
                **session,
                "geometry": {
                    "x": area["X"],
                    "y": area["Y"],
                    "width": area["WIDTH"],
                    "height": area["HEIGHT"],
                },
                "latest_screenshot": str(LATEST_SHOT),
            },
            indent=2,
        )
    )


def logs(args) -> None:
    path = RUNTIME / f"{args.process}.log"
    if not path.exists():
        raise UiError(f"no log at {path}")
    lines = path.read_text(errors="replace").splitlines()
    print("\n".join(lines[-args.lines :]))


def terminate(pid: int, expected: str) -> None:
    if not process_alive(pid):
        return
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        return
    if expected.encode() not in cmdline:
        raise UiError(f"refusing to stop pid {pid}: not a {expected} process")
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if process_alive(pid):
        os.killpg(pid, signal.SIGKILL)


def stop(_args) -> None:
    if not SESSION_PATH.exists():
        print("not running")
        return
    session = load_session(require_live=False)
    terminate(session["app_pid"], "app.py")
    terminate(session["xvfb_pid"], "Xvfb")
    SESSION_PATH.unlink(missing_ok=True)
    print("stopped")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Send native input to dailyfold on Xvfb and capture the result."
    )
    commands = result.add_subparsers(dest="command", required=True)

    start_parser = commands.add_parser("start", help="start Xvfb and dailyfold")
    start_parser.set_defaults(run=start)

    click_parser = commands.add_parser("click", help="click window-relative pixels")
    click_parser.add_argument("x", type=int)
    click_parser.add_argument("y", type=int)
    click_parser.add_argument("--button", type=int, default=1)
    click_parser.set_defaults(run=click)

    move_parser = commands.add_parser("move", help="move the mouse")
    move_parser.add_argument("x", type=int)
    move_parser.add_argument("y", type=int)
    move_parser.set_defaults(run=move)

    drag_parser = commands.add_parser("drag", help="drag between two points")
    drag_parser.add_argument("x1", type=int)
    drag_parser.add_argument("y1", type=int)
    drag_parser.add_argument("x2", type=int)
    drag_parser.add_argument("y2", type=int)
    drag_parser.add_argument("--button", type=int, default=1)
    drag_parser.set_defaults(run=drag)

    type_parser = commands.add_parser("type", help="type text into the focused widget")
    type_parser.add_argument("text")
    type_parser.add_argument("--delay", type=int, default=12, help="milliseconds per key")
    type_parser.set_defaults(run=type_text)

    key_parser = commands.add_parser("key", help="send xdotool key names")
    key_parser.add_argument("keys", nargs="+")
    key_parser.set_defaults(run=key)

    shot_parser = commands.add_parser("shot", help="capture the current GTK window")
    shot_parser.add_argument("path", nargs="?")
    shot_parser.set_defaults(run=shot)

    status_parser = commands.add_parser("status", help="show session and window geometry")
    status_parser.set_defaults(run=status)

    logs_parser = commands.add_parser("logs", help="show recent process logs")
    logs_parser.add_argument("process", choices=("app", "xvfb"), default="app", nargs="?")
    logs_parser.add_argument("--lines", type=int, default=40)
    logs_parser.set_defaults(run=logs)

    stop_parser = commands.add_parser("stop", help="stop dailyfold and Xvfb")
    stop_parser.set_defaults(run=stop)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.run(args)
    except (UiError, subprocess.CalledProcessError) as exc:
        print(f"ui: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.rstrip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

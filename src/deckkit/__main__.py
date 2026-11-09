"""deckkit commands and the optional graphical interface."""

import argparse
import json
import sys

from . import __version__, cyberpunk, profiles
from .install import Installer
from .paths import Paths


def parser():
    command = argparse.ArgumentParser(prog="deckkit")
    command.add_argument("--version", action="version", version=__version__)
    command.add_argument("--home", help=argparse.SUPPRESS)
    commands = command.add_subparsers(dest="action")
    commands.add_parser("catalog")

    for action in ("installer", "install", "remove", "status", "profile"):
        subcommand = commands.add_parser(action)
        subcommand.add_argument(
            "package_id", nargs="?", default="cyberpunk2077"
        )
        if action == "install":
            subcommand.add_argument("--allow-restart", action="store_true")
        elif action == "profile":
            subcommand.add_argument("--fps", choices=("uncapped", "45"))
            subcommand.add_argument(
                "--ui-scale", type=int, choices=cyberpunk.UI_SCALES
            )

    for action in ("launch", "restore"):
        subcommand = commands.add_parser(action)
        if action == "launch":
            subcommand.add_argument("--no-ui", action="store_true")
        subcommand.add_argument("package_id")
        subcommand.add_argument("command", nargs=argparse.REMAINDER)

    commands.add_parser("update-runtime")
    return command


def status(installer, package_id):
    receipt = installer.load_receipt(package_id)
    if receipt is None:
        return {"installed": False}

    result = {"installed": True, "version": receipt["version"]}
    if receipt["manifest"]["kind"] == "cyberpunk2077":
        fps_limit, ui_scale = cyberpunk.selected(receipt)
        result.update(fps_limit=fps_limit, ui_scale=ui_scale)

    return result


def configure(installer, args):
    receipt = installer.load_receipt(args.package_id)
    if receipt is None:
        raise RuntimeError("The Cyberpunk package is not installed.")

    fps_limit, ui_scale = cyberpunk.selected(receipt)
    if args.fps is not None:
        fps_limit = None if args.fps == "uncapped" else int(args.fps)
    if args.ui_scale is not None:
        ui_scale = args.ui_scale

    return profiles.apply(installer, args.package_id, fps_limit, ui_scale)


def main():
    command_parser = parser()
    args = command_parser.parse_args()
    installer = Installer(Paths(args.home))

    try:
        if args.action in (None, "catalog", "installer"):
            from .catalog_ui import catalog

            initial = args.package_id if args.action == "installer" else None
            catalog(installer, initial)
        elif args.action == "install":
            result = installer.install(
                args.package_id, allow_restart=args.allow_restart
            )
            print(json.dumps(result))
        elif args.action == "remove":
            print(json.dumps(installer.remove(args.package_id)))
        elif args.action == "status":
            print(json.dumps(status(installer, args.package_id)))
        elif args.action == "profile":
            print(json.dumps(configure(installer, args)))
        elif args.action == "update-runtime":
            installer.refresh()
            installer.update_runtime()
        else:
            from .launcher import launch, restore

            command = args.command
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                command_parser.error("The Steam game command is missing.")

            if args.action == "launch":
                launch(
                    installer,
                    args.package_id,
                    command,
                    interactive=not args.no_ui,
                )
            else:
                restore(installer, args.package_id, command)
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        StopIteration,
    ) as error:
        graphical = args.action in (None, "catalog", "installer", "restore")
        graphical |= args.action == "launch" and not args.no_ui
        if graphical:
            from .ui import error_window

            error_window(str(error))
        else:
            print(str(error), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

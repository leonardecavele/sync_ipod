from __future__ import annotations

import os
import shutil
import subprocess
import sys

from pathlib import Path


PROJECT_ROOT: Path = Path(__file__).resolve().parent

SRC_PATHS: dict[str, Path] = {
    "SRC_PYTHON_DIR": PROJECT_ROOT / "python_script",
    "SRC_CONFIG_FILE": PROJECT_ROOT / "config" / "config.json",
    "SRC_RUNNER_FILE": PROJECT_ROOT / "runner" / "sync_ipod",
    "SRC_SERVICE_FILE": PROJECT_ROOT / "service" / "sync_ipod@.service",
    "SRC_UDEV_FILE": PROJECT_ROOT / "udev_rule" / "90_sync_ipod.rules",
}

DST_PATHS: dict[str, Path] = {
    "DST_PYTHON_DIR": Path("/opt/sync_ipod"),
    "DST_CONFIG_DIR": Path("/etc/sync_ipod"),
    "DST_CONFIG_FILE": Path("/etc/sync_ipod/config.json"),
    "DST_RUNNER_FILE": Path("/usr/local/bin/sync_ipod"),
    "DST_SERVICE_FILE": Path("/etc/systemd/system/sync_ipod@.service"),
    "DST_UDEV_FILE": Path("/etc/udev/rules.d/90_sync_ipod.rules"),
}


def run(command: list[str]) -> None:
    result = subprocess.run(command, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}")


def is_sudo() -> None:
    if os.geteuid() != 0:
        print("this script must be run with sudo", file=sys.stderr)
        raise SystemExit(1)


def copy_python_script() -> None:
    source_dir: Path = SRC_PATHS["SRC_PYTHON_DIR"]
    destination_dir: Path = DST_PATHS["DST_PYTHON_DIR"]

    destination_dir.mkdir(parents=True, exist_ok=True)

    for source_file in sorted(source_dir.glob("*.py")):
        destination_file: Path = destination_dir / source_file.name
        shutil.copy2(source_file, destination_file)
        print(f"copied {source_file} to {destination_file}")


def copy_file(src_key: str, dst_key: str, label: str, executable: bool = False) -> None:
    source_file: Path = SRC_PATHS[src_key]
    destination_file: Path = DST_PATHS[dst_key]

    destination_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, destination_file)

    if executable:
        destination_file.chmod(0o755)

    print(f"copied {label} {source_file} to {destination_file}")


def reload_system() -> None:
    run(["systemctl", "daemon-reload"])
    run(["udevadm", "control", "--reload-rules"])

    print("reloaded systemd daemon")
    print("reloaded udev rules")


def main() -> int:
    is_sudo()

    copy_python_script()
    copy_file("SRC_CONFIG_FILE", "DST_CONFIG_FILE", "config")
    copy_file("SRC_RUNNER_FILE", "DST_RUNNER_FILE", "runner", executable=True)
    copy_file("SRC_SERVICE_FILE", "DST_SERVICE_FILE", "service")
    copy_file("SRC_UDEV_FILE", "DST_UDEV_FILE", "udev rule")
    reload_system()

    print("successfully installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import json
import shutil
import subprocess
import sys
import re
import subprocess
import time

from pathlib import Path
from typing import Any

from error import ErrorCode

PROGRESS_RE: re.Pattern[str] = re.compile(
    r"^\s*(?P<size>\S+)\s+(?P<percent>\d+)%\s+(?P<speed>\S+)\s+(?P<eta>\S+)"
)

PWR_LED_PATH: Path = Path("/sys/class/leds/PWR")


def start_power_led_status() -> None:
    try:
        (PWR_LED_PATH / "trigger").write_text("actpwr", encoding="utf-8")
        (PWR_LED_PATH / "delay_on").write_text("150", encoding="utf-8")
        (PWR_LED_PATH / "delay_off").write_text("150", encoding="utf-8")
    except OSError as exc:
        print(f"unable to start PWR LED blink: {exc}", flush=True)


def stop_power_led_status() -> None:
    try:
        (PWR_LED_PATH / "trigger").write_text("none", encoding="utf-8")
    except OSError as exc:
        print(f"unable to restore PWR LED trigger: {exc}", flush=True)


def notify_status(message: str) -> None:
    subprocess.run(
        ["systemd-notify", f"--status={message}"],
        check=False,
        text=True,
    )


def handle_rsync_line(line: str, last_notified_percent: int | None) -> int | None:
    cleaned_line: str = line.strip()
    if not cleaned_line:
        return last_notified_percent

    match = PROGRESS_RE.match(cleaned_line)
    if match is not None:
        percent: int = int(match.group("percent"))
        size: str = match.group("size")
        speed: str = match.group("speed")
        eta: str = match.group("eta")

        if percent != last_notified_percent:
            message: str = (
                f"Syncing music: {percent}% - {size} copied - {speed} - ETA {eta}"
            )
            notify_status(message)
            print(message, flush=True)
            return percent

        return last_notified_percent

    print(cleaned_line, flush=True)
    return last_notified_percent


def sync_music(library: Path, music_dir: Path) -> None:
    music_dir.mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen(
        [
            "rsync",
            "-rt",
            "--delete",
            "--inplace",
            "--outbuf=L",
            "--info=progress2,name0",
            f"{library}/",
            f"{music_dir}/",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if process.stdout is None:
        raise RuntimeError("unable to read rsync output")

    buffer: str = ""
    last_notified_percent: int | None = None

    while True:
        chunk: str = process.stdout.read(1)

        if chunk == "":
            if buffer:
                last_notified_percent = handle_rsync_line(
                    buffer,
                    last_notified_percent,
                )
            break

        if chunk in {"\r", "\n"}:
            last_notified_percent = handle_rsync_line(
                buffer,
                last_notified_percent,
            )
            buffer = ""
            continue

        buffer += chunk

    return_code: int = process.wait()
    if return_code != 0:
        raise RuntimeError(f"rsync failed with exit code {return_code}")

    notify_status("Music sync complete")
    print("music sync complete", flush=True)


def sync_playlists(playlists: Path, playlists_dir: Path) -> None:
    allowed_extensions: set[str] = {".m3u8", ".fpl"}

    playlists_dir.mkdir(parents=True, exist_ok=True)

    for existing_path in playlists_dir.iterdir():
        if existing_path.is_file() and existing_path.suffix.lower() in allowed_extensions:
            existing_path.unlink()

    for playlist_path in sorted(playlists.rglob("*")):
        if not playlist_path.is_file():
            continue
        if playlist_path.suffix.lower() not in allowed_extensions:
            continue

        destination_path: Path = playlists_dir / playlist_path.name
        shutil.copy2(playlist_path, destination_path)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 sync_ipod.py <mount_point>", flush=True, file=sys.stderr)
        return ErrorCode.INVALID_USAGE_ERROR

    script_directory: Path = Path(__file__).resolve().parent
    config_path: Path = Path("/etc/sync_ipod/config.json")
    config: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))

    mount: Path = Path(sys.argv[1]).resolve()
    library_root: Path = Path(config["library_root"]).resolve()
    music_source: Path = (library_root / config["music_source"]).resolve()
    playlists_source: Path = (library_root / config["playlists_source"]).resolve()
    music_dest_name: str = config["music_dest"]
    playlists_dest_name: str = config["playlists_dest"]
    rockbox_marker: str = config["rockbox_marker"]

    if not mount.exists():
        print(f"mount does not exist: {mount}", flush=True, file=sys.stderr)
        return ErrorCode.UNEXISTING_FILE_ERROR
    if not library_root.exists():
        print(f"library root does not exist: {library_root}", flush=True, file=sys.stderr)
        return ErrorCode.UNEXISTING_FILE_ERROR
    if not music_source.exists():
        print(f"music source does not exist: {music_source}", flush=True, file=sys.stderr)
        return ErrorCode.UNEXISTING_FILE_ERROR
    if not playlists_source.exists():
        print(f"playlists source does not exist: {playlists_source}", flush=True, file=sys.stderr)
        return ErrorCode.UNEXISTING_FILE_ERROR
    if not (mount / rockbox_marker).exists():
        print(f"not a rockbox device: {mount}", flush=True, file=sys.stderr)
        return ErrorCode.UNEXISTING_FILE_ERROR

    music_dir: Path = mount / music_dest_name
    playlists_dir: Path = mount / playlists_dest_name

    start_power_led_status()
    print(f"syncing music from {music_source} to {music_dir}")
    sync_music(music_source, music_dir)

    print(f"syncing playlists from {playlists_source} to {playlists_dir}")
    sync_playlists(playlists_source, playlists_dir)
    stop_power_led_status()

    print("successfully synced")
    return ErrorCode.NO_ERROR


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        stop_power_led_status()
        sys.extit(1)

import json
import select
import shutil
import subprocess
import sys
import re
import time

from pathlib import Path
from typing import Any

from error import ErrorCode

PROGRESS_RE: re.Pattern[str] = re.compile(
    r"^\s*(?P<size>\S+)\s+(?P<percent>\d+)%\s+(?P<speed>\S+)\s+(?P<eta>\S+)"
)

PWR_LED_PATH: Path = Path("/sys/class/leds/PWR")
RSYNC_INACTIVITY_TIMEOUT_SECONDS: float = 120.0
RSYNC_POLL_INTERVAL_SECONDS: float = 1.0


def start_power_led_status() -> None:
    try:
        (PWR_LED_PATH / "trigger").write_text("actpwr", encoding="utf-8")
    except OSError as exc:
        print(f"unable to start PWR LED blink: {exc}", flush=True)


def stop_power_led_status() -> None:
    try:
        (PWR_LED_PATH / "trigger").write_text("none", encoding="utf-8")
    except OSError as exc:
        print(f"unable to restore PWR LED trigger: {exc}", flush=True)


def notify_status(message: str) -> None:
    try:
        result = subprocess.run(
            ["systemd-notify", "--pid=parent", f"--status={message}"],
            check=False,
        )
        if result.returncode != 0:
            print(
                f"systemd-notify failed with exit code {result.returncode}",
                flush=True,
            )
    except OSError as exc:
        print(f"unable to notify status: {exc}", flush=True)


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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

    try:
        process: subprocess.Popen[str] = subprocess.Popen(
            [
                "rsync",
                "-rt",
                "--modify-window=2",
                "--stats",
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
    except OSError as exc:
        raise RuntimeError(f"unable to start rsync: {exc}") from exc

    if process.stdout is None:
        stop_process(process)
        raise RuntimeError("unable to read rsync output")

    buffer: str = ""
    last_notified_percent: int | None = None
    last_activity_time: float = time.monotonic()

    try:
        while True:
            ready_to_read, _, _ = select.select(
                [process.stdout],
                [],
                [],
                RSYNC_POLL_INTERVAL_SECONDS,
            )

            if ready_to_read:
                chunk: str = process.stdout.read(1)

                if chunk == "":
                    if buffer:
                        last_notified_percent = handle_rsync_line(
                            buffer,
                            last_notified_percent,
                        )
                    break

                last_activity_time = time.monotonic()

                if chunk in {"\r", "\n"}:
                    last_notified_percent = handle_rsync_line(
                        buffer,
                        last_notified_percent,
                    )
                    buffer = ""
                    continue

                buffer += chunk
                continue

            if process.poll() is not None:
                if buffer:
                    last_notified_percent = handle_rsync_line(
                        buffer,
                        last_notified_percent,
                    )
                break

            elapsed_without_output: float = time.monotonic() - last_activity_time
            if elapsed_without_output >= RSYNC_INACTIVITY_TIMEOUT_SECONDS:
                timeout_message: str = (
                    "Music sync stalled: no rsync output for 120 seconds, aborting"
                )
                notify_status(timeout_message)
                print(timeout_message, flush=True)
                stop_process(process)
                raise TimeoutError(timeout_message)

        return_code: int = process.wait()
        if return_code != 0:
            raise RuntimeError(f"rsync failed with exit code {return_code}")

    except Exception:
        stop_process(process)
        raise
    finally:
        process.stdout.close()

    notify_status("Music sync complete")
    print("music sync complete", flush=True)


def sync_playlists(playlists: Path, playlists_dir: Path) -> None:
    allowed_extensions: set[str] = {".fpl"}

    try:
        playlists_dir.mkdir(parents=True, exist_ok=True)

        for existing_path in playlists_dir.iterdir():
            if (
                existing_path.is_file()
                and existing_path.suffix.lower() in allowed_extensions
            ):
                existing_path.unlink()

        for playlist_path in sorted(playlists.rglob("*")):
            if not playlist_path.is_file():
                continue
            if playlist_path.suffix.lower() not in allowed_extensions:
                continue

            destination_path: Path = playlists_dir / playlist_path.name
            shutil.copy2(playlist_path, destination_path)

    except OSError as exc:
        raise RuntimeError(f"playlist sync failed: {exc}") from exc


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 sync_ipod.py <mount_point>", flush=True, file=sys.stderr)
        return ErrorCode.INVALID_USAGE_ERROR

    script_directory: Path = Path(__file__).resolve().parent

    try:
        config_path: Path = Path("/etc/sync_ipod/config.json")
        config: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unable to read config: {exc}", flush=True, file=sys.stderr)
        return ErrorCode.UNEXISTING_FILE_ERROR

    try:
        mount: Path = Path(sys.argv[1]).resolve()
        library_root: Path = Path(config["library_root"]).resolve()
        music_source: Path = (library_root / config["music_source"]).resolve()
        playlists_source: Path = (library_root / config["playlists_source"]).resolve()
        music_dest_name: str = config["music_dest"]
        playlists_dest_name: str = config["playlists_dest"]
        rockbox_marker: str = config["rockbox_marker"]
    except KeyError as exc:
        print(f"missing config key: {exc}", flush=True, file=sys.stderr)
        return ErrorCode.INVALID_USAGE_ERROR

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
    try:
        print(f"syncing music from {music_source} to {music_dir}", flush=True)
        sync_music(music_source, music_dir)

        print(f"syncing playlists from {playlists_source} to {playlists_dir}", flush=True)
        sync_playlists(playlists_source, playlists_dir)
    finally:
        stop_power_led_status()

    print("successfully synced", flush=True)
    return ErrorCode.NO_ERROR


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        stop_power_led_status()
        print("sync interrupted", flush=True, file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        stop_power_led_status()
        print(f"error: {exc}", flush=True, file=sys.stderr)
        sys.exit(1)

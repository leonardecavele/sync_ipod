import json
import shutil
import subprocess
import sys

from pathlib import Path
from typing import Any

from error import ErrorCode


def sync_music(library: Path, music_dir: Path) -> None:
    music_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "rsync",
            "-rt",
            "--delete",
            "--human-readable",
            "--inplace",
            "--info=stats2,name0",
            f"{library}/",
            f"{music_dir}/",
        ],
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rsync failed with exit code {result.returncode}")


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

    print(f"syncing music from {music_source} to {music_dir}")
    sync_music(music_source, music_dir)

    print(f"syncing playlists from {playlists_source} to {playlists_dir}")
    sync_playlists(playlists_source, playlists_dir)

    print("successfully synced")
    return ErrorCode.NO_ERROR


if __name__ == "__main__":
    sys.exit(main())

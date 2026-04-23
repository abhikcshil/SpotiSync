from __future__ import annotations

from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import ID3, TCON
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE


class MetadataWriteError(Exception):
    pass


class MetadataGenreWriter:
    SUPPORTED_SUFFIXES = {".mp3", ".flac", ".m4a", ".mp4", ".wav"}

    def write_genre(self, file_path: str, genre: str) -> None:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise MetadataWriteError(f"File not found: {path}")
        if not path.is_file():
            raise MetadataWriteError(f"Not a file: {path}")

        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED_SUFFIXES:
            raise MetadataWriteError(f"Unsupported metadata format: {suffix or 'unknown'}")

        try:
            if suffix == ".flac":
                audio = FLAC(path)
                audio["genre"] = [genre]
                audio.save()
                return

            if suffix in {".m4a", ".mp4"}:
                audio = MP4(path)
                audio["\xa9gen"] = [genre]
                audio.save()
                return

            if suffix in {".mp3", ".wav"}:
                audio = MP3(path, ID3=ID3) if suffix == ".mp3" else WAVE(path)
                if audio.tags is None:
                    audio.add_tags()
                audio.tags.delall("TCON")
                audio.tags.add(TCON(encoding=3, text=[genre]))
                audio.save()
                return
        except PermissionError as exc:
            raise MetadataWriteError(f"File is not writable: {path}") from exc
        except OSError as exc:
            raise MetadataWriteError(f"Unable to write metadata: {exc}") from exc
        except Exception as exc:
            raise MetadataWriteError(str(exc)) from exc

        raise MetadataWriteError(f"Unsupported metadata format: {suffix or 'unknown'}")

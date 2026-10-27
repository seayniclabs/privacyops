"""Local store: one JSON file, read-modify-write under a lock, atomic replace.

Every write goes to a temp file in the same folder, is fsynced, then replaces the old file in
one step. A failed write leaves the previous file intact. An unreadable file is never
overwritten: tools return ``storage.corrupt_store`` so the person can repair or move it.
Unknown top-level keys survive every write.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from .errors import PrivacyOpsError

try:  # POSIX file locks; on platforms without fcntl the in-process lock still applies.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = 1
T = TypeVar("T")
_thread_lock = threading.Lock()


def atomic_write(path: Path, text: str) -> None:
    """Write text to path via a temp file and an atomic rename. Mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.path = self.dir / "privacyops.json"
        self.lock_path = self.dir / ".privacyops.lock"
        self.letters_dir = self.dir / "letters"

    def ensure_dirs(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.letters_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as e:
            raise PrivacyOpsError(
                "storage", "unwritable",
                f"cannot create the data folder {self.dir} ({e.strerror or type(e).__name__}).",
                "set PRIVACYOPS_DATA_DIR to a folder you can write to.",
            )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.ensure_dirs()
        with _thread_lock:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "disputes": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise PrivacyOpsError(
                "storage", "corrupt_store",
                f"cannot read {self.path.name} ({type(e).__name__}); nothing was changed.",
                "move the file aside or restore it from a backup, then try again.",
            )
        if not isinstance(data, dict) or not isinstance(data.get("disputes"), dict):
            raise PrivacyOpsError(
                "storage", "corrupt_store",
                f"{self.path.name} does not have the expected structure; nothing was changed.",
                "move the file aside or restore it from a backup, then try again.",
            )
        return data

    def read(self) -> dict:
        if not self.dir.exists():  # reading never creates the data folder
            return {"schema_version": SCHEMA_VERSION, "disputes": {}}
        with self._locked():
            return self._read()

    def update(self, fn: Callable[[dict], T]) -> T:
        """Run fn on the current data and save it. If fn raises, nothing is written."""
        with self._locked():
            data = self._read()
            result = fn(data)
            data["schema_version"] = SCHEMA_VERSION
            try:
                atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True))
            except OSError as e:
                raise PrivacyOpsError(
                    "storage", "write_failed",
                    f"could not save {self.path.name} ({e.strerror or type(e).__name__}); "
                    "the previous data is unchanged.",
                    "check that PRIVACYOPS_DATA_DIR is writable and has free space.",
                )
            return result

"""Logging with the legacy semantics (console levels + optional log file)."""
from __future__ import annotations

import datetime
import enum
import sys


class LogLevel(enum.IntEnum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR")


class Logger:
    def __init__(self) -> None:
        self.console_level = LogLevel.INFO
        self._file = None
        self.warnings = 0
        self.errors = 0
        # When True, INFO/DEBUG messages go to stderr instead of stdout so
        # that machine-readable stdout (e.g. `list --json`) stays clean.
        self.info_to_stderr = False

    def set_console_level(self, level: LogLevel) -> None:
        self.console_level = level

    def open_file(self, path: str) -> None:
        try:
            self._file = open(path, "a", encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Cannot open log file for writing: {path}: {exc}") from exc

    def log(self, level: LogLevel, message: str) -> None:
        if level == LogLevel.WARNING:
            self.warnings += 1
        if level == LogLevel.ERROR:
            self.errors += 1
        if level >= self.console_level:
            if level >= LogLevel.WARNING or self.info_to_stderr:
                stream = sys.stderr
            else:
                stream = sys.stdout
            stream.write(f"[{_NAMES[int(level)]}] {message}\n")
        if self._file is not None:
            try:
                stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._file.write(f"{stamp} [{_NAMES[int(level)]}] {message}\n")
                self._file.flush()
            except OSError:
                try:
                    self._file.close()
                finally:
                    self._file = None
                sys.stderr.write("[WARNING] Writing to the log file failed; file logging disabled.\n")

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None


LOG = Logger()


def log_debug(m: str) -> None: LOG.log(LogLevel.DEBUG, m)
def log_info(m: str) -> None: LOG.log(LogLevel.INFO, m)
def log_warn(m: str) -> None: LOG.log(LogLevel.WARNING, m)
def log_error(m: str) -> None: LOG.log(LogLevel.ERROR, m)

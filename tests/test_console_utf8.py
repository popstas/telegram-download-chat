"""On Windows the default stdio encoding follows the locale codepage (e.g.
cp1251), so a log line with a Cyrillic chat name is emitted as single-byte
mojibake that the GUI (reading the subprocess pipe as UTF-8) shows as
replacement characters. The CLI must force UTF-8 on its stdout/stderr.
"""

import sys

from telegram_download_chat.cli import _reconfigure_utf8, configure_console_utf8


class _FakeStream:
    def __init__(self, raises=None):
        self.calls = []
        self._raises = raises

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises


def test_reconfigure_sets_utf8():
    s = _FakeStream()
    _reconfigure_utf8(s)
    assert s.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_reconfigure_without_method_is_noop():
    # A stream that can't be reconfigured (e.g. None/replaced stdout in a
    # frozen app) must not raise.
    _reconfigure_utf8(object())
    _reconfigure_utf8(None)


def test_reconfigure_swallows_errors():
    # An unsupported underlying stream raises; the helper must swallow it.
    _reconfigure_utf8(_FakeStream(raises=ValueError("detached buffer")))
    _reconfigure_utf8(_FakeStream(raises=OSError("no buffer")))


def test_configure_console_reconfigures_both_streams(monkeypatch):
    out, err = _FakeStream(), _FakeStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    configure_console_utf8()
    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]

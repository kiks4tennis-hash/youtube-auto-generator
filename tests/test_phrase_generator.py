import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))

from media.subtitle_generator import SubtitleCue, _format_timestamp, write_srt  # noqa: E402


def test_format_timestamp():
    assert _format_timestamp(0) == "00:00:00,000"
    assert _format_timestamp(65.5) == "00:01:05,500"
    assert _format_timestamp(3661.123) == "01:01:01,123"


def test_write_srt(tmp_path):
    cues = [
        SubtitleCue(start=0.0, end=1.5, text="Hello"),
        SubtitleCue(start=1.9, end=3.0, text="World"),
    ]
    out_path = tmp_path / "test.srt"
    write_srt(cues, out_path)
    content = out_path.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\nHello" in content
    assert "2\n00:00:01,900 --> 00:00:03,000\nWorld" in content

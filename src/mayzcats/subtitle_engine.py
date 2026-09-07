from __future__ import annotations

import math
import re
from pathlib import Path
from typing import TypeVar

from .models import Narration, ScriptPackage, WordTiming

T = TypeVar("T", WordTiming, str)

ASS_HEADER = """[Script Info]
Title: MayzCats V1
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0
; Fontname=Montserrat

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,Montserrat,64,&H0000FFFF,&H00FFFFFF,&H00181818,&H78000000,-1,0,0,0,100,100,0,0,1,5,1,2,120,120,260,1
Style: Watermark,Montserrat,42,&HCCFFFFFF,&HCCFFFFFF,&H66000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,9,30,42,34,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


class AssSubtitleEngine:
    def render_text(self, narration: Narration, package: ScriptPackage, *, duration: float) -> str:
        lines = [ASS_HEADER.rstrip()]
        lines.append(self._dialogue(3, 0.0, duration, "Watermark", self._escape("MayzCats")))
        if narration.words:
            lines.extend(self._word_events(narration.words, duration=duration))
        else:
            lines.extend(self._phrase_events(package.script, duration))
        return "\n".join(lines) + "\n"

    def write(
        self,
        path: Path,
        narration: Narration,
        package: ScriptPackage,
        *,
        duration: float,
    ) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render_text(narration, package, duration=duration), encoding="utf-8")
        return path

    def _word_events(self, words: list[WordTiming], *, duration: float) -> list[str]:
        events: list[str] = []
        windows = self._windows(words)
        for index, window in enumerate(windows):
            start = window[0].start
            end = (
                windows[index + 1][0].start
                if index + 1 < len(windows)
                else max(duration, words[-1].end)
            )
            end = max(end, start + 0.05)
            events.append(
                self._dialogue(
                    0,
                    start,
                    end,
                    "Subtitle",
                    self._karaoke_text(window, start=start, end=end),
                )
            )
        return events

    def _phrase_events(self, script: str, duration: float) -> list[str]:
        words = re.findall(r"\S+", script)
        if not words:
            return []
        chunks = self._windows(words)
        total_words = len(words)
        cursor = 0.0
        events: list[str] = []
        for index, chunk in enumerate(chunks):
            end = (
                duration
                if index == len(chunks) - 1
                else cursor + duration * len(chunk) / total_words
            )
            events.append(
                self._dialogue(
                    0,
                    cursor,
                    end,
                    "Subtitle",
                    self._wrap_text(chunk, max_line_characters=18),
                )
            )
            cursor = end
        return events

    def _karaoke_text(self, words: list[WordTiming], *, start: float, end: float) -> str:
        rendered: list[str] = []
        for index, word in enumerate(words):
            boundary = words[index + 1].start if index + 1 < len(words) else end
            duration = max(1, int(round((boundary - max(word.start, start)) * 100)))
            rendered.append(r"{\kf" + str(duration) + "}" + self._escape(word.text))
        return self._wrap_text(rendered, raw_words=[word.text for word in words])

    @staticmethod
    def _windows(
        items: list[T], *, max_words: int = 4, max_characters: int = 32
    ) -> list[list[T]]:
        windows: list[list[T]] = []
        current: list[T] = []
        current_characters = 0
        for item in items:
            text = item.text if isinstance(item, WordTiming) else str(item)
            projected = current_characters + (1 if current else 0) + len(text)
            if current and (len(current) >= max_words or projected > max_characters):
                windows.append(current)
                current = []
                current_characters = 0
            current.append(item)
            current_characters += (1 if len(current) > 1 else 0) + len(text)
        if current:
            windows.append(current)
        return windows

    def _wrap_text(
        self,
        words: list[str],
        *,
        raw_words: list[str] | None = None,
        max_line_characters: int = 18,
    ) -> str:
        if not words:
            return ""
        visible = raw_words or words
        escaped = words if raw_words is not None else [self._escape(word) for word in words]
        total = sum(len(word) for word in visible) + len(visible) - 1
        if len(words) == 1 or total <= max_line_characters:
            return " ".join(escaped)
        break_at = min(
            range(1, len(words)),
            key=lambda index: (
                max(
                    sum(len(word) for word in visible[:index]) + index - 1,
                    sum(len(word) for word in visible[index:]) + len(visible) - index - 1,
                ),
                abs(
                    (sum(len(word) for word in visible[:index]) + index - 1)
                    - (
                        sum(len(word) for word in visible[index:])
                        + len(visible)
                        - index
                        - 1
                    )
                ),
            ),
        )
        return " ".join(escaped[:break_at]) + r"\N" + " ".join(escaped[break_at:])

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("{", "(").replace("}", ")").replace("\n", r"\N")

    @staticmethod
    def _dialogue(layer: int, start: float, end: float, style: str, text: str) -> str:
        return f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{text}"


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    centiseconds = int(math.floor(seconds * 100 + 0.5))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"

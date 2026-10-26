"""자막 글자 처리: 줄바꿈과 단어 시각 맞추기.

줄바꿈 규칙은 static/js/util.js의 wrapText와 똑같아야 한다 (미리보기 = 렌더).
    - 공백 단위로 단어를 이어 붙이다가 max_chars를 넘으면 다음 줄
    - 단어 하나가 max_chars보다 길면 글자 단위로 자른다
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\S+")


def wrap_text(text: str, max_chars: int) -> list[str]:
    return [" ".join(line) for line in wrap_tokens(text, max_chars)]


def wrap_tokens(text: str, max_chars: int) -> list[list[str]]:
    """줄마다 단어 목록을 돌려준다 (긴 단어는 잘린 조각이 단어처럼 들어간다)."""
    max_chars = max(1, int(max_chars))
    lines: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for token in _TOKEN.findall(text or ""):
        while len(token) > max_chars:
            if cur:
                lines.append(cur)
                cur, cur_len = [], 0
            lines.append([token[:max_chars]])
            token = token[max_chars:]
        if not token:
            continue
        added = len(token) + (1 if cur else 0)
        if cur and cur_len + added > max_chars:
            lines.append(cur)
            cur, cur_len = [token], len(token)
        else:
            cur.append(token)
            cur_len += added
    if cur:
        lines.append(cur)
    return lines


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def align_words_to_lines(text: str, words: list[str], max_chars: int) -> list[int] | None:
    """단어(받아쓰기 단위)마다 몇 번째 줄에 들어가는지 돌려준다. 글자가 서로 안 맞으면 None.
    받아쓰기 단어와 자막 줄은 공백만 빼면 같은 글자열이라, 공백을 뺀 글자 위치로 맞춘다."""
    if squash(text) != squash("".join(words)):
        return None
    line_of_char: list[int] = []
    for i, line in enumerate(wrap_tokens(text, max_chars)):
        line_of_char += [i] * len(squash("".join(line)))
    result, pos = [], 0
    for w in words:
        n = len(squash(w))
        if n == 0:
            result.append(line_of_char[pos - 1] if pos else 0)
            continue
        result.append(line_of_char[pos])
        pos += n
    return result

/* 자막 글자 처리: 줄바꿈과 단어 시각 맞추기.
   서버 src/vibecut/domain/text.py와 같은 규칙이어야 한다 (미리보기 자막 줄바꿈 = 렌더 자막 줄바꿈).
   같은 사례 파일(tests/fixtures/wrap_cases.json)로 양쪽을 함께 검사한다 (tests/js/wrap.test.mjs).
   화면 상태를 쓰지 않는 순수 함수만 둔다 (Node 테스트가 그대로 읽는다). */

export function squash(text) {
  return String(text || "").replace(/\s+/g, "");
}

// 공백 단위로 이어 붙이다가 maxChars를 넘으면 다음 줄. 단어 하나가 maxChars보다 길면 글자 단위로 자른다.
export function wrapTokens(text, maxChars) {
  maxChars = Math.max(1, Math.floor(maxChars || 1));
  const lines = [];
  let cur = [], curLen = 0;
  for (let token of String(text || "").split(/\s+/).filter(Boolean)) {
    while (token.length > maxChars) {
      if (cur.length) { lines.push(cur); cur = []; curLen = 0; }
      lines.push([token.slice(0, maxChars)]);
      token = token.slice(maxChars);
    }
    if (!token) continue;
    const added = token.length + (cur.length ? 1 : 0);
    if (cur.length && curLen + added > maxChars) {
      lines.push(cur); cur = [token]; curLen = token.length;
    } else {
      cur.push(token); curLen += added;
    }
  }
  if (cur.length) lines.push(cur);
  return lines;
}

export function wrapText(text, maxChars) {
  return wrapTokens(text, maxChars).map(line => line.join(" "));
}

/* 단어마다 몇 번째 줄인지 (서버 align_words_to_lines와 같음). 글자가 안 맞으면 null */
export function alignWordsToLines(text, words, maxChars) {
  if (squash(text) !== squash(words.join(""))) return null;
  const lineOfChar = [];
  wrapTokens(text, maxChars).forEach((line, i) => {
    for (let n = squash(line.join("")).length; n > 0; n--) lineOfChar.push(i);
  });
  const out = [];
  let pos = 0;
  for (const w of words) {
    const n = squash(w).length;
    if (n === 0) { out.push(pos ? lineOfChar[pos - 1] : 0); continue; }
    out.push(lineOfChar[pos]);
    pos += n;
  }
  return out;
}

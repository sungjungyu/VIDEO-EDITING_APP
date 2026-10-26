// 화면 자막 줄바꿈(static/js)이 서버(vibecut/edit/text.py)와 같은지 확인한다 (미리보기 = 렌더).
// 같은 사례 파일 tests/wrap_cases.json을 pytest(tests/test_text_and_ass.py)도 쓴다.
// 실행: node tests/js/wrap.test.mjs   (Node 18 이상, 의존 패키지 없음)

import { readFileSync } from "node:fs";
import { wrapText } from "../../static/js/util.js";
import { alignWordsToLines } from "../../static/js/style.js";

const cases = JSON.parse(readFileSync(new URL("../wrap_cases.json", import.meta.url), "utf8"));
let failed = 0;

for (const c of cases) {
  const got = wrapText(c.text, c.width);
  if (JSON.stringify(got) !== JSON.stringify(c.lines)) {
    failed++;
    console.error("줄바꿈 다름:", JSON.stringify(c), "→", JSON.stringify(got));
  }
}

const aligned = alignWordsToLines("오늘은 카페에 왔어요 라떼가 맛있어요", ["오늘은", "카페에", "왔어요", "라떼가", "맛있어요"], 10);
if (JSON.stringify(aligned) !== JSON.stringify([0, 0, 1, 1, 2])) {
  failed++;
  console.error("단어-줄 맞춤 다름:", aligned);
}
if (alignWordsToLines("다른 글자", ["오늘은"], 10) !== null) {
  failed++;
  console.error("글자가 다르면 null이어야 합니다");
}

if (failed) {
  console.error(`실패 ${failed}건`);
  process.exit(1);
}
console.log(`통과: 줄바꿈 ${cases.length}건 + 단어-줄 맞춤 2건`);

// 화면 배경음악 크기(web/js/core/mix.js)가 서버(src/vibecut/domain/mix.py)와 같은지 확인한다 (미리보기 = 렌더).
// 같은 사례 파일 tests/fixtures/mix_cases.json을 pytest(tests/unit/domain/test_mix.py)도 쓴다.
// 실행: node tests/js/mix.test.mjs

import { readFileSync } from "node:fs";
import { gainAt } from "../../web/js/core/mix.js";

const data = JSON.parse(readFileSync(new URL("../fixtures/mix_cases.json", import.meta.url), "utf8"));
let failed = 0;
for (const c of data.cases) {
  const got = gainAt(c.t, data.spans, data.volume, data.duck_level, true, data.duration);
  if (Math.abs(got - c.gain) > 1e-6) {
    failed++;
    console.error(`크기 다름: t=${c.t} 기대 ${c.gain} → ${got}`);
  }
}
if (failed) process.exit(1);
console.log(`배경음악 크기 ${data.cases.length}개 사례 모두 같음`);

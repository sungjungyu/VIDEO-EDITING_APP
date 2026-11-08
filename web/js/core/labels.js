/* 화면에 보이는 용어를 한 곳에. 서버 값(판단 이유 등)은 그대로 두고 보여 줄 말만 바꾼다. */

/* 문장 판단 이유 (서버 analysis/judge.py의 CUT_REASONS·KEEP_REASONS) → 화면 이름 */
export const REASON_LABEL = {
  NG: "NG",
  반복: "반복",
  군더더기: "군더더기",
  지시어: "촬영 지시",
  핵심: "핵심",
  일반: "일반",
};

/* 뺀 이유 한 줄 설명 (판단에 note가 없을 때) */
export const REASON_HELP = {
  NG: "바로 뒤에서 같은 말을 다시 했어요",
  반복: "같은 말을 되풀이했어요",
  군더더기: "음, 어 같은 의미 없는 말이에요",
  지시어: "\"다시 갈게\" 같은 촬영 지시예요",
};

export const reasonLabel = r => REASON_LABEL[r] || r;

/* 뺀 문장의 이유. 사람이 직접 뺀 문장은 판단 이유가 '일반·핵심'으로 남아 있으므로 '직접 뺌'으로 보여 준다 */
const CUT_REASONS = ["NG", "반복", "군더더기", "지시어"];
REASON_LABEL.직접 = "직접 뺌";
REASON_HELP.직접 = "내가 뺀 문장이에요";
export const cutReason = d => (CUT_REASONS.includes(d.reason) ? d.reason : "직접");

export const KEEP_LABEL = "살림";
export const CUT_LABEL = "뺌";

export const SOURCE_LABEL = { ai: "AI 판단", rule: "규칙 판단", user: "내가 바꿈" };

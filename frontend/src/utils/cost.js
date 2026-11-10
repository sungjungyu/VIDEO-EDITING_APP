// Gemini 비용 계산 (화면 표시용). 서버가 주는 모델별 토큰(metrics.ai_usage.tokens_by_model)에 단가를 곱한다.
// 단가: https://ai.google.dev/gemini-api/docs/pricing (2026-11-10 확인, 유료 등급, USD / 100만 토큰)
// gemini-3.5-flash는 지원 중단되어 gemini-3.6-flash로 처리되므로 3.6 Flash 단가. 계산 근거는 docs/측정기록.md

export const KRW_PER_USD = 1400;   // 표시용 환율 (이 값 하나만 바꾸면 된다)

const PRICES = {
  'gemini-3.5-flash':      [0.75, 3.75],   // = gemini-3.6-flash
  'gemini-3.6-flash':      [0.75, 3.75],
  'gemini-3.5-flash-lite': [0.30, 2.50],
  'gemini-3.5-transcribe': [2.00, 12.00],
};

/** tokens_by_model {모델: [입력, 출력]} → { usd, krw, unknown: [단가 모르는 모델] } */
export function geminiCost(tokensByModel) {
  let usd = 0;
  const unknown = [];
  for (const [model, [input, output]] of Object.entries(tokensByModel ?? {})) {
    const price = PRICES[model];
    if (!price) { unknown.push(model); continue; }
    usd += (input / 1e6) * price[0] + (output / 1e6) * price[1];
  }
  return { usd, krw: Math.round(usd * KRW_PER_USD), unknown };
}

/** 원화 표시: ₩1,234 (1원 미만이면 ₩0) */
export function fmtKrw(krw) {
  return `₩${Math.round(krw).toLocaleString('ko-KR')}`;
}

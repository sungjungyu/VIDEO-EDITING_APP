import { describe, it, expect } from 'vitest';
import { geminiCost, fmtKrw, KRW_PER_USD } from './cost.js';

describe('geminiCost', () => {
  it('모델별 토큰에 단가를 곱한다 (docs/측정기록.md 1시간 재측정 값)', () => {
    const { usd, unknown } = geminiCost({
      'gemini-3.5-transcribe': [89718, 6217],
      'gemini-3.5-flash': [29175, 2600],
    });
    expect(usd).toBeCloseTo(0.2857, 3);
    expect(unknown).toEqual([]);
  });

  it('원화는 환율 상수 하나로 바꾼다', () => {
    const { usd, krw } = geminiCost({ 'gemini-3.5-flash-lite': [1_000_000, 0] });
    expect(usd).toBeCloseTo(0.30, 6);
    expect(krw).toBe(Math.round(0.30 * KRW_PER_USD));
  });

  it('단가를 모르는 모델은 빼고 알려 준다, 비어 있으면 0원', () => {
    expect(geminiCost({ 'gemini-9-pro': [10, 10] })).toEqual({ usd: 0, krw: 0, unknown: ['gemini-9-pro'] });
    expect(geminiCost(undefined).krw).toBe(0);
  });

  it('표시 형식', () => {
    expect(fmtKrw(400)).toBe('₩400');
    expect(fmtKrw(12345.6)).toBe('₩12,346');
  });
});

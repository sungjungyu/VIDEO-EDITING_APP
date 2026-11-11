import { describe, it, expect } from 'vitest';
import { geminiCost, fmtKrw, KRW_PER_USD, combinedCost } from './cost.js';

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

  it('이번 실행 비용 = 분석 + 목차 정리 합 (1시간 원본: 분석 $0.2857 + AI 트리 $0.0291, docs/측정기록.md)', () => {
    const analysis = { requests: 15, cache_hits: 0, tokens_by_model: {
      'gemini-3.5-transcribe': [89718, 6217], 'gemini-3.5-flash': [29175, 2600] } };
    const tree = { requests: 3, cache_hits: 0, tokens_by_model: { 'gemini-3.5-flash': [26988, 2357] } };
    const run = combinedCost([['분석', analysis], ['목차 정리', tree]]);
    expect(run.usd).toBeCloseTo(0.2857 + 0.0291, 3);
    expect(run.krw).toBe(Math.round(run.usd * KRW_PER_USD));           // 약 441원 = 400 + 41
    expect(run.lines[0]).toBe('분석 ₩400 (Gemini 15회, 캐시 0회)');
    expect(run.lines[1]).toBe('목차 정리 ₩41 (Gemini 3회, 캐시 0회)');
    expect(run.lines[2]).toBe('합계 Gemini 18회 · 캐시 0회');
    expect(combinedCost([['분석', analysis], ['목차 정리', null]]).lines[1]).toBe('목차 정리 ₩0 (AI를 쓰지 않음)');
  });

  it('표시 형식', () => {
    expect(fmtKrw(400)).toBe('₩400');
    expect(fmtKrw(12345.6)).toBe('₩12,346');
  });
});

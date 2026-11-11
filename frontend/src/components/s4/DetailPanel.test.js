import { describe, it, expect } from 'vitest';
import { playRange } from './DetailPanel.jsx';

// 클립 c01(타임라인 0~100초)과 c02(타임라인 100초부터) 위 장면들. 시각: start/end = 전체 타임라인 초, clip_start = 클립 안 초
const s1 = { id: 's1', level: 'scene', clip_id: 'c01', start: 10, end: 30, clip_start: 10, clip_end: 30, children: [] };
const s2 = { id: 's2', level: 'scene', clip_id: 'c01', start: 30, end: 55, clip_start: 30, clip_end: 55, children: [] };
const s3 = { id: 's3', level: 'scene', clip_id: 'c02', start: 100, end: 120, clip_start: 0, clip_end: 20, children: [] };
const task = { id: 'k1', level: 'task', start: 10, end: 120, children: [{ id: 'a1', level: 'situation', children: [s1, s2, s3] }] };

describe('playRange (S4 상세 패널 재생 구간)', () => {
  it('L4는 그 장면 구간, 클립 안 초로 바꿀 offset', () => {
    expect(playRange(s3)).toEqual({ clipId: 'c02', offset: 100, start: 100, end: 120 });
  });

  it('상위 노드는 첫 장면부터 같은 클립의 마지막 장면 끝까지', () => {
    expect(playRange(task)).toEqual({ clipId: 'c01', offset: 0, start: 10, end: 55 });
  });

  it('클립 시각이 없는 mock 장면은 재생하지 않는다', () => {
    expect(playRange({ id: 'sc1', level: 'scene', start: 10, end: 38, children: [] })).toBeNull();
  });
});

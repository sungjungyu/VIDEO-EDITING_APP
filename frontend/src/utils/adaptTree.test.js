import { describe, it, expect } from 'vitest';
import { adaptTree, defaultSelection } from './adaptTree.js';
import { getTotalSec, toggle } from '../logic/selection.js';

// 서버 GET /projects/{id}/tree 모양 (L1 1개 → L2 1개 → L3 1개 → L4 2개)
const doc = {
  meta: { source: 'rules', counts: { l4: 2 } },
  tree: [{
    id: 'p01', level: 1, title: '카페 (1차 방문)', start: 0, end: 40, summary: '', tags: [], children: [{
      id: 'p01-f01', level: 2, title: '주문 흐름', start: 0, end: 40, summary: '', tags: [], children: [{
        id: 'p01-f01-a01', level: 3, title: '주문', start: 0, end: 40, summary: '', tags: [], children: [
          { id: 's0001', level: 4, title: '안녕하세요 아메리카노 한 잔', start: 0, end: 22, clip_id: 'c01', clip_start: 0, clip_end: 22,
            place: '카페', action: '주문', people: ['민수'], tags: ['대사'], children: [],
            lines: [{ id: 't0001', start: 1, end: 3, text: '안녕하세요 아메리카노 한 잔', speaker: null }] },
          { id: 's0002', level: 4, title: '카페에서 기다린다', start: 22, end: 40, clip_id: 'c01', clip_start: 22, clip_end: 40,
            place: '카페', action: '대기', people: [], tags: ['말 없음'], children: [], lines: [] },
        ],
      }],
    }],
  }],
};

describe('adaptTree', () => {
  it('서버 단계 번호를 화면 단계 이름으로, L4 대사는 sentences로 모은다', () => {
    const t = adaptTree(doc);
    const l4 = t.tree[0].children[0].children[0].children;
    expect(t.tree[0].level).toBe('topic');
    expect(t.tree[0].children[0].level).toBe('task');
    expect(t.tree[0].children[0].children[0].level).toBe('situation');
    expect(l4.map(n => n.level)).toEqual(['scene', 'scene']);
    expect(l4[0]).toMatchObject({ activity: '주문', sentence_ids: ['t0001'], clip_id: 'c01', children: [] });
    expect(t.sentences).toEqual([{ id: 't0001', start: 1, end: 3, text: '안녕하세요 아메리카노 한 잔', speaker: '' }]);
    expect(t.duration).toBe(40);
  });

  it('처음 선택은 모든 장면 켜짐, 화면 선택 로직(켜기·끄기·합계)이 그대로 동작한다', () => {
    const t = adaptTree(doc);
    const sel = defaultSelection(t, 600);
    expect(sel.target_sec).toBe(600);
    expect(Object.keys(sel.nodes)).toEqual(['s0001', 's0002']);
    expect(getTotalSec(sel.nodes, t)).toBe(40);
    const { nodes } = toggle(sel.nodes, 's0002', t);
    expect(getTotalSec(nodes, t)).toBe(22);
  });
});

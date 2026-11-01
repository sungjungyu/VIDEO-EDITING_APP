import { describe, it, expect } from 'vitest';
import {
  getNodeState,
  toggle,
  setLock,
  getTotalSec,
  applyAISelection,
  findNodePath,
  computeAutoCompress,
} from './selection.js';

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

const tree = {
  tree: [{
    id: 't1', level: 'topic', start: 0, end: 300,
    children: [{
      id: 'k1', level: 'task', start: 0, end: 300,
      children: [{
        id: 's1', level: 'situation', start: 0, end: 300,
        children: [
          { id: 'sc1', level: 'scene', start: 0,   end: 100 },
          { id: 'sc2', level: 'scene', start: 100, end: 200 },
          { id: 'sc3', level: 'scene', start: 200, end: 300 },
        ]
      }]
    }]
  }]
};

// ---------------------------------------------------------------------------
// getNodeState
// ---------------------------------------------------------------------------

describe('getNodeState', () => {
  it('all leaves on → group state is "on"', () => {
    const nodes = {
      sc1: { state: 'on',  by: 'user', lock: null, reason: null },
      sc2: { state: 'on',  by: 'user', lock: null, reason: null },
      sc3: { state: 'on',  by: 'user', lock: null, reason: null },
    };
    expect(getNodeState(nodes, 's1', tree)).toBe('on');
  });

  it('mixed leaves → group state is "partial"', () => {
    const nodes = {
      sc1: { state: 'on',  by: 'user', lock: null, reason: null },
      sc2: { state: 'off', by: 'user', lock: null, reason: null },
      sc3: { state: 'on',  by: 'user', lock: null, reason: null },
    };
    expect(getNodeState(nodes, 's1', tree)).toBe('partial');
  });

  it('all leaves off → group state is "off"', () => {
    const nodes = {
      sc1: { state: 'off', by: 'user', lock: null, reason: null },
      sc2: { state: 'off', by: 'user', lock: null, reason: null },
      sc3: { state: 'off', by: 'user', lock: null, reason: null },
    };
    expect(getNodeState(nodes, 's1', tree)).toBe('off');
  });

  it('scene directly: sc1 on → "on"', () => {
    const nodes = {
      sc1: { state: 'on', by: 'user', lock: null, reason: null },
    };
    expect(getNodeState(nodes, 'sc1', tree)).toBe('on');
  });

  it('scene missing from nodes → "off"', () => {
    expect(getNodeState({}, 'sc1', tree)).toBe('off');
  });
});

// ---------------------------------------------------------------------------
// toggle (scene)
// ---------------------------------------------------------------------------

describe('toggle (scene)', () => {
  it('sc1 on → becomes off, by:"user"', () => {
    const nodes = {
      sc1: { state: 'on', by: 'ai', lock: null, reason: null },
    };
    const { nodes: next, blocked } = toggle(nodes, 'sc1', tree);
    expect(blocked).toBe(false);
    expect(next.sc1.state).toBe('off');
    expect(next.sc1.by).toBe('user');
  });

  it('sc1 off → becomes on, by:"user"', () => {
    const nodes = {
      sc1: { state: 'off', by: 'ai', lock: null, reason: null },
    };
    const { nodes: next, blocked } = toggle(nodes, 'sc1', tree);
    expect(blocked).toBe(false);
    expect(next.sc1.state).toBe('on');
    expect(next.sc1.by).toBe('user');
  });

  it('sc1 on + lock:must_include → blocked:true, nodes unchanged', () => {
    const nodes = {
      sc1: { state: 'on', by: 'user', lock: 'must_include', reason: null },
    };
    const { nodes: next, blocked } = toggle(nodes, 'sc1', tree);
    expect(blocked).toBe(true);
    expect(next).toBe(nodes); // same reference → unchanged
  });

  it('sc1 off + lock:must_exclude → blocked:true, nodes unchanged', () => {
    const nodes = {
      sc1: { state: 'off', by: 'user', lock: 'must_exclude', reason: null },
    };
    const { nodes: next, blocked } = toggle(nodes, 'sc1', tree);
    expect(blocked).toBe(true);
    expect(next).toBe(nodes);
  });
});

// ---------------------------------------------------------------------------
// toggle (group)
// ---------------------------------------------------------------------------

describe('toggle (group)', () => {
  it('all scenes on → toggle s1 → all off', () => {
    const nodes = {
      sc1: { state: 'on', by: 'user', lock: null, reason: null },
      sc2: { state: 'on', by: 'user', lock: null, reason: null },
      sc3: { state: 'on', by: 'user', lock: null, reason: null },
    };
    const { nodes: next, blocked } = toggle(nodes, 's1', tree);
    expect(blocked).toBe(false);
    expect(next.sc1.state).toBe('off');
    expect(next.sc2.state).toBe('off');
    expect(next.sc3.state).toBe('off');
  });

  it('not all on → toggle s1 → all on', () => {
    const nodes = {
      sc1: { state: 'off', by: 'ai', lock: null, reason: null },
      sc2: { state: 'on',  by: 'ai', lock: null, reason: null },
      sc3: { state: 'off', by: 'ai', lock: null, reason: null },
    };
    const { nodes: next, blocked } = toggle(nodes, 's1', tree);
    expect(blocked).toBe(false);
    expect(next.sc1.state).toBe('on');
    expect(next.sc2.state).toBe('on');
    expect(next.sc3.state).toBe('on');
  });

  it('sc2 has lock:must_exclude → toggle s1 toward on → sc2 stays off', () => {
    const nodes = {
      sc1: { state: 'off', by: 'ai', lock: null,           reason: null },
      sc2: { state: 'off', by: 'ai', lock: 'must_exclude', reason: null },
      sc3: { state: 'off', by: 'ai', lock: null,           reason: null },
    };
    const { nodes: next } = toggle(nodes, 's1', tree);
    expect(next.sc1.state).toBe('on');
    expect(next.sc2.state).toBe('off'); // locked, not changed
    expect(next.sc3.state).toBe('on');
  });

  it('sc1 has lock:must_include, toggle s1 toward off → sc1 stays on', () => {
    const nodes = {
      sc1: { state: 'on', by: 'user', lock: 'must_include', reason: null },
      sc2: { state: 'on', by: 'user', lock: null,           reason: null },
      sc3: { state: 'on', by: 'user', lock: null,           reason: null },
    };
    const { nodes: next } = toggle(nodes, 's1', tree);
    // All were on → going off. sc1 has must_include → skip.
    expect(next.sc1.state).toBe('on');
    expect(next.sc2.state).toBe('off');
    expect(next.sc3.state).toBe('off');
  });
});

// ---------------------------------------------------------------------------
// setLock
// ---------------------------------------------------------------------------

describe('setLock', () => {
  it('setLock on sc1 must_include → sc1 state=on, lock=must_include', () => {
    const nodes = {
      sc1: { state: 'off', by: 'ai', lock: null, reason: null },
    };
    const next = setLock(nodes, 'sc1', 'must_include', tree);
    expect(next.sc1.state).toBe('on');
    expect(next.sc1.lock).toBe('must_include');
  });

  it('setLock on s1 must_exclude → all three scenes state=off, lock=must_exclude', () => {
    const nodes = {
      sc1: { state: 'on', by: 'user', lock: null, reason: null },
      sc2: { state: 'on', by: 'user', lock: null, reason: null },
      sc3: { state: 'on', by: 'user', lock: null, reason: null },
    };
    const next = setLock(nodes, 's1', 'must_exclude', tree);
    expect(next.sc1.state).toBe('off');
    expect(next.sc1.lock).toBe('must_exclude');
    expect(next.sc2.state).toBe('off');
    expect(next.sc2.lock).toBe('must_exclude');
    expect(next.sc3.state).toBe('off');
    expect(next.sc3.lock).toBe('must_exclude');
  });

  it('setLock must_include then setLock null → lock=null, state unchanged', () => {
    const nodes = {
      sc1: { state: 'off', by: 'ai', lock: null, reason: null },
    };
    const afterInclude = setLock(nodes, 'sc1', 'must_include', tree);
    expect(afterInclude.sc1.state).toBe('on');
    expect(afterInclude.sc1.lock).toBe('must_include');

    const afterNull = setLock(afterInclude, 'sc1', null, tree);
    expect(afterNull.sc1.lock).toBe(null);
    expect(afterNull.sc1.state).toBe('on'); // state unchanged
  });
});

// ---------------------------------------------------------------------------
// getTotalSec
// ---------------------------------------------------------------------------

describe('getTotalSec', () => {
  it('sc1 on (100s), sc2 off, sc3 on (100s) → 200', () => {
    const nodes = {
      sc1: { state: 'on',  by: 'user', lock: null, reason: null },
      sc2: { state: 'off', by: 'user', lock: null, reason: null },
      sc3: { state: 'on',  by: 'user', lock: null, reason: null },
    };
    expect(getTotalSec(nodes, tree)).toBe(200);
  });

  it('all off → 0', () => {
    const nodes = {
      sc1: { state: 'off', by: 'user', lock: null, reason: null },
      sc2: { state: 'off', by: 'user', lock: null, reason: null },
      sc3: { state: 'off', by: 'user', lock: null, reason: null },
    };
    expect(getTotalSec(nodes, tree)).toBe(0);
  });

  it('all on → 300', () => {
    const nodes = {
      sc1: { state: 'on', by: 'user', lock: null, reason: null },
      sc2: { state: 'on', by: 'user', lock: null, reason: null },
      sc3: { state: 'on', by: 'user', lock: null, reason: null },
    };
    expect(getTotalSec(nodes, tree)).toBe(300);
  });
});

// ---------------------------------------------------------------------------
// applyAISelection
// ---------------------------------------------------------------------------

describe('applyAISelection', () => {
  it('apply [{id:sc1, state:on, reason:test}] → sc1 state=on, by:ai, reason=test', () => {
    const nodes = {
      sc1: { state: 'off', by: 'user', lock: null, reason: null },
    };
    const next = applyAISelection(nodes, [{ id: 'sc1', state: 'on', reason: 'test' }]);
    expect(next.sc1.state).toBe('on');
    expect(next.sc1.by).toBe('ai');
    expect(next.sc1.reason).toBe('test');
  });

  it('locked sc2: apply to sc2 → unchanged', () => {
    const nodes = {
      sc2: { state: 'off', by: 'user', lock: 'must_exclude', reason: null },
    };
    const next = applyAISelection(nodes, [{ id: 'sc2', state: 'on', reason: 'ai wants on' }]);
    expect(next.sc2.state).toBe('off');
    expect(next.sc2.by).toBe('user');
    expect(next.sc2.lock).toBe('must_exclude');
  });

  it('node not in nodes (new entry) → gets added with ai metadata', () => {
    const nodes = {};
    const next = applyAISelection(nodes, [{ id: 'sc3', state: 'on', reason: 'important' }]);
    expect(next.sc3.state).toBe('on');
    expect(next.sc3.by).toBe('ai');
    expect(next.sc3.reason).toBe('important');
  });
});

// ---------------------------------------------------------------------------
// toggle (group) — 잠금 섞인 케이스 Space 두 번
// ---------------------------------------------------------------------------

describe('toggle (group) — Space 두 번', () => {
  it('must_exclude 섞인 그룹: Space 두 번 → unlocked off→on→off, locked 유지', () => {
    const nodes0 = {
      sc1: { state: 'off', by: 'user', lock: null,           reason: null },
      sc2: { state: 'off', by: 'user', lock: null,           reason: null },
      sc3: { state: 'off', by: 'user', lock: 'must_exclude', reason: null },
    };
    // First Space: unlocked 모두 off → targetState = on
    const { nodes: nodes1 } = toggle(nodes0, 's1', tree);
    expect(nodes1.sc1.state).toBe('on');
    expect(nodes1.sc2.state).toBe('on');
    expect(nodes1.sc3.state).toBe('off'); // must_exclude 유지

    // Second Space: unlocked (sc1, sc2) 모두 on → targetState = off
    const { nodes: nodes2 } = toggle(nodes1, 's1', tree);
    expect(nodes2.sc1.state).toBe('off');
    expect(nodes2.sc2.state).toBe('off');
    expect(nodes2.sc3.state).toBe('off'); // must_exclude 유지
  });

  it('must_include 섞인 그룹: Space 두 번 → 잠금 장면 계속 on', () => {
    const nodes0 = {
      sc1: { state: 'off', by: 'user', lock: null,           reason: null },
      sc2: { state: 'off', by: 'user', lock: null,           reason: null },
      sc3: { state: 'on',  by: 'user', lock: 'must_include', reason: null },
    };
    // First Space: unlocked (sc1, sc2) off → targetState = on
    const { nodes: nodes1 } = toggle(nodes0, 's1', tree);
    expect(nodes1.sc1.state).toBe('on');
    expect(nodes1.sc2.state).toBe('on');
    expect(nodes1.sc3.state).toBe('on'); // must_include 유지

    // Second Space: unlocked (sc1, sc2) 모두 on → targetState = off
    const { nodes: nodes2 } = toggle(nodes1, 's1', tree);
    expect(nodes2.sc1.state).toBe('off');
    expect(nodes2.sc2.state).toBe('off');
    expect(nodes2.sc3.state).toBe('on'); // must_include → off 시도 skip
  });
});

// ---------------------------------------------------------------------------
// getNodeState — 장면 1개 off → partial
// ---------------------------------------------------------------------------

describe('getNodeState — partial', () => {
  it('장면 1개만 off → 상위 상태 partial', () => {
    const nodes = {
      sc1: { state: 'on',  by: 'user', lock: null, reason: null },
      sc2: { state: 'off', by: 'user', lock: null, reason: null },
      sc3: { state: 'on',  by: 'user', lock: null, reason: null },
    };
    expect(getNodeState(nodes, 's1', tree)).toBe('partial');
    expect(getNodeState(nodes, 'k1', tree)).toBe('partial');
    expect(getNodeState(nodes, 't1', tree)).toBe('partial');
  });
});

// ---------------------------------------------------------------------------
// computeAutoCompress
// ---------------------------------------------------------------------------

// 장면 길이가 고르지 않은 mock: 10s, 12s, 15s, 20s, 60s
// 마지막 60s 장면은 합계가 (57+60=117s) vs (57s) 중 목표 60s에 더 가까운 57s를 선택
const edgeTree = {
  tree: [{
    id: 'et1', level: 'topic', start: 0, end: 117,
    children: [{
      id: 'ek1', level: 'task', start: 0, end: 117,
      children: [{
        id: 'es1', level: 'situation', start: 0, end: 117,
        children: [
          { id: 'esc1', level: 'scene', start: 0,   end: 10  }, // 10s
          { id: 'esc2', level: 'scene', start: 10,  end: 22  }, // 12s
          { id: 'esc3', level: 'scene', start: 22,  end: 37  }, // 15s
          { id: 'esc4', level: 'scene', start: 37,  end: 57  }, // 20s
          { id: 'esc5', level: 'scene', start: 57,  end: 117 }, // 60s (큰 장면)
        ],
      }],
    }],
  }],
};

describe('computeAutoCompress', () => {
  it('큰 장면(60s) 포함 시 ±10% 판단: 57s가 더 가까우므로 60s 장면 제외', () => {
    const sel = { target_sec: 60, nodes: {} };
    const result = computeAutoCompress(sel, edgeTree);
    const map = Object.fromEntries(result.map(r => [r.id, r.state]));
    // 10+12+15+20 = 57s (목표 60s와 3s 차이)
    // 10+12+15+20+60 = 117s (목표 60s와 57s 차이) → 57s 쪽이 더 가까움
    expect(map.esc1).toBe('on');
    expect(map.esc2).toBe('on');
    expect(map.esc3).toBe('on');
    expect(map.esc4).toBe('on');
    expect(map.esc5).toBe('off'); // 60s 장면 제외
    // 합계 ±10% 확인
    const total = 10 + 12 + 15 + 20; // 57s
    expect(Math.abs(total - 60) / 60).toBeLessThan(0.1);
  });

  it('잠금 장면은 결과에서 제외되고 상태 유지', () => {
    // esc1(10s) must_include → lockedOnSec=10, 나머지 greedy
    const sel = {
      target_sec: 60,
      nodes: { esc1: { state: 'on', by: 'user', lock: 'must_include', reason: null } },
    };
    const result = computeAutoCompress(sel, edgeTree);
    // result는 unlocked 장면만 포함 (esc2~esc5)
    expect(result.find(r => r.id === 'esc1')).toBeUndefined();
    expect(result.length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// findNodePath
// ---------------------------------------------------------------------------

describe('findNodePath', () => {
  it('finds path to leaf scene', () => {
    expect(findNodePath('sc1', tree)).toEqual(['t1', 'k1', 's1', 'sc1']);
  });

  it('finds path to mid-level node', () => {
    expect(findNodePath('s1', tree)).toEqual(['t1', 'k1', 's1']);
  });

  it('finds path to root node', () => {
    expect(findNodePath('t1', tree)).toEqual(['t1']);
  });

  it('returns null for unknown id', () => {
    expect(findNodePath('nonexistent', tree)).toBeNull();
  });
});

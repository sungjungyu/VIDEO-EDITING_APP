// 서버 4단 트리(GET /projects/{id}/tree) → S4 화면 트리 형식 (mock/tree.json과 같은 모양)
//   서버 노드: { id, level: 1|2|3|4, title, start, end, summary, children, (L4) clip_id, place, action, people, lines }
//   화면 노드: { id, level: 'topic'|'task'|'situation'|'scene', title, start, end, summary, children,
//              (scene) clip_id, place, activity, people, sentence_ids }
//   시각은 둘 다 '전체 타임라인 초'. L4 대사(lines)는 sentences 목록으로 모으고 장면에는 id만 남긴다.

const LEVELS = { 1: 'topic', 2: 'task', 3: 'situation', 4: 'scene' };

export function adaptTree(doc) {
  const sentences = [];
  const seen = new Set();

  function node(n) {
    const out = {
      id: n.id, level: LEVELS[n.level] ?? String(n.level), title: n.title, start: n.start, end: n.end,
      summary: n.summary ?? '', tags: n.tags ?? [],
    };
    if (n.level === 4) {
      for (const line of n.lines ?? []) {
        if (seen.has(line.id)) continue;
        seen.add(line.id);
        sentences.push({ id: line.id, start: line.start, end: line.end, text: line.text, speaker: line.speaker ?? '' });
      }
      Object.assign(out, {
        clip_id: n.clip_id, clip_start: n.clip_start, clip_end: n.clip_end,
        place: n.place ?? '', activity: n.action ?? '', people: n.people ?? [],
        sentence_ids: (n.lines ?? []).map(l => l.id), children: [],
      });
    } else {
      out.children = (n.children ?? []).map(node);
    }
    return out;
  }

  const tree = (doc?.tree ?? []).map(node);
  sentences.sort((a, b) => a.start - b.start);
  const duration = tree.length ? tree[tree.length - 1].end : 0;
  return { tree, sentences, speakers: [], duration, meta: doc?.meta ?? {}, notes: doc?.notes ?? [] };
}

/** 모든 L4 장면을 켠 선택 (실제 모드의 처음 상태). 켜기·끄기·잠금은 화면에서만 바꾼다 */
export function defaultSelection(treeData, targetSec) {
  const nodes = {};
  const walk = (list) => list.forEach(n => {
    if (n.level === 'scene') nodes[n.id] = { state: 'on', by: 'user', reason: null, lock: null };
    else walk(n.children ?? []);
  });
  walk(treeData?.tree ?? []);
  return { target_sec: targetSec ?? null, nodes };
}

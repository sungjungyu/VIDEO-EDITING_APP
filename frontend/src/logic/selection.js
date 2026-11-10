// Pure functions for scene selection state management.
// No React, no side effects.
//
// Tree node shape: { id, level: 'topic'|'task'|'situation'|'scene', start, end, children?, title }
// Selection node shape: nodes[sceneId] = { state:'on'|'off', by:'user'|'ai', lock:'must_include'|'must_exclude'|null, reason:string|null }
// Only 'scene' (leaf) nodes are stored in nodes. Upper-level states are computed.

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _findNode(id, treeArr) {
  for (const node of treeArr) {
    if (node.id === id) return node;
    if (node.children && node.children.length > 0) {
      const found = _findNode(id, node.children);
      if (found) return found;
    }
  }
  return null;
}

function _leafIds(node) {
  if (!node.children || node.children.length === 0) {
    // This is a leaf (scene)
    return [node.id];
  }
  const ids = [];
  for (const child of node.children) {
    ids.push(..._leafIds(child));
  }
  return ids;
}

// ---------------------------------------------------------------------------
// Exported functions
// ---------------------------------------------------------------------------

/**
 * Returns 'on' | 'off' | 'partial' for any node.
 * For scene nodes: direct lookup (undefined → 'off').
 * For group nodes: all leaves on → 'on', all off → 'off', mixed → 'partial'.
 */
export function getNodeState(nodes, nodeId, treeData) {
  const roots = treeData.tree || treeData;
  const node = _findNode(nodeId, roots);
  if (!node) return 'off';

  if (node.level === 'scene') {
    return nodes[nodeId]?.state ?? 'off';
  }

  const leafIds = _leafIds(node);
  if (leafIds.length === 0) return 'off';

  let onCount = 0;
  for (const id of leafIds) {
    if ((nodes[id]?.state ?? 'off') === 'on') onCount++;
  }

  if (onCount === 0) return 'off';
  if (onCount === leafIds.length) return 'on';
  return 'partial';
}

/**
 * Toggle selection for a node (scene or group).
 * Returns { nodes: newNodes, blocked: boolean }.
 *
 * Scene:
 *   - Flip on↔off, set by:'user'.
 *   - If locked and the flip is blocked (must_include when currently on,
 *     or must_exclude when currently off) → blocked:true, nodes unchanged.
 *
 * Group:
 *   - All on → all off; else → all on.
 *   - Skip locked leaves that conflict with the target direction
 *     (must_include if going off, must_exclude if going on).
 *   - Set by:'user' on changed leaves.
 */
export function toggle(nodes, nodeId, treeData) {
  const roots = treeData.tree || treeData;
  const node = _findNode(nodeId, roots);
  if (!node) return { nodes, blocked: false };

  if (node.level === 'scene') {
    const current = nodes[nodeId]?.state ?? 'off';
    const lock = nodes[nodeId]?.lock ?? null;

    // Check if the flip is blocked by a lock
    if (lock === 'must_include' && current === 'on') {
      return { nodes, blocked: true };
    }
    if (lock === 'must_exclude' && current === 'off') {
      return { nodes, blocked: true };
    }

    const newState = current === 'on' ? 'off' : 'on';
    const newNodes = {
      ...nodes,
      [nodeId]: {
        ...(nodes[nodeId] ?? { lock: null, reason: null }),
        state: newState,
        by: 'user',
      },
    };
    return { nodes: newNodes, blocked: false };
  }

  // Group node: direction determined by unlocked leaves only.
  // All unlocked on → turn all off. Otherwise → turn all on.
  // Locked leaves are excluded from the decision (but still skipped in the loop below).
  const leafIds = _leafIds(node);
  const unlockedLeafIds = leafIds.filter(id => !(nodes[id]?.lock));
  const allUnlockedOn = unlockedLeafIds.length > 0 &&
    unlockedLeafIds.every(id => (nodes[id]?.state ?? 'off') === 'on');
  const targetState = allUnlockedOn ? 'off' : 'on';

  const newNodes = { ...nodes };
  for (const id of leafIds) {
    const lock = newNodes[id]?.lock ?? null;
    // Skip locked leaves that conflict with target direction
    if (targetState === 'off' && lock === 'must_include') continue;
    if (targetState === 'on' && lock === 'must_exclude') continue;

    newNodes[id] = {
      ...(newNodes[id] ?? { lock: null, reason: null }),
      state: targetState,
      by: 'user',
    };
  }

  return { nodes: newNodes, blocked: false };
}

/**
 * Apply a lock type to all leaf scenes under nodeId.
 * lockType: 'must_include' | 'must_exclude' | null
 *   - must_include  → state = 'on'
 *   - must_exclude  → state = 'off'
 *   - null          → state unchanged
 * Returns new nodes object.
 */
export function setLock(nodes, nodeId, lockType, treeData) {
  const roots = treeData.tree || treeData;
  const node = _findNode(nodeId, roots);
  if (!node) return nodes;

  const leafIds = _leafIds(node);
  const newNodes = { ...nodes };

  for (const id of leafIds) {
    const existing = newNodes[id] ?? { state: 'off', by: 'user', lock: null, reason: null };
    let newState = existing.state;
    if (lockType === 'must_include') newState = 'on';
    else if (lockType === 'must_exclude') newState = 'off';
    // null → state unchanged

    newNodes[id] = {
      ...existing,
      state: newState,
      lock: lockType,
    };
  }

  return newNodes;
}

/**
 * Sum of (end - start) for all scenes where nodes[id]?.state === 'on'.
 */
export function getTotalSec(nodes, treeData) {
  const roots = treeData.tree || treeData;

  // Collect all scene nodes from tree
  function collectScenes(arr) {
    const scenes = [];
    for (const node of arr) {
      if (node.level === 'scene') {
        scenes.push(node);
      } else if (node.children && node.children.length > 0) {
        scenes.push(...collectScenes(node.children));
      }
    }
    return scenes;
  }

  const scenes = collectScenes(roots);
  let total = 0;
  for (const scene of scenes) {
    if ((nodes[scene.id]?.state ?? 'off') === 'on') {
      total += scene.end - scene.start;
    }
  }
  return total;
}

/**
 * Apply AI selection results to nodes.
 * aiResult: Array<{ id, state, reason }>
 * For each entry: if nodes[id]?.lock is set → skip; else set state, by:'ai', reason.
 * Returns new nodes object.
 */
export function applyAISelection(nodes, aiResult) {
  const newNodes = { ...nodes };
  for (const entry of aiResult) {
    const existing = newNodes[entry.id];
    if (existing?.lock) continue; // skip locked
    newNodes[entry.id] = {
      ...(existing ?? { lock: null }),
      state: entry.state,
      by: 'ai',
      reason: entry.reason ?? null,
    };
  }
  return newNodes;
}

/**
 * Pure computation for AI auto-compress.
 * Greedy shortest-first selection respecting target_sec * 1.05 ceiling.
 * When a scene would push past the budget, picks whichever option
 * (with or without it) lands closer to target_sec.
 * Warns to console if final total is outside target ±10%.
 * Returns Array<{ id, state:'on'|'off', reason }> for unlocked scenes only.
 */
export function computeAutoCompress(selection, treeData) {
  const targetSec = selection.target_sec ?? 600;
  const nodes     = selection.nodes ?? {};
  const ceiling   = targetSec * 1.05;

  function collectScenes(arr) {
    const scenes = [];
    for (const node of arr) {
      if (node.level === 'scene') {
        scenes.push(node);
      } else if (node.children && node.children.length > 0) {
        scenes.push(...collectScenes(node.children));
      }
    }
    return scenes;
  }

  const roots          = treeData.tree || treeData;
  const allScenes      = collectScenes(roots);
  const lockedScenes   = allScenes.filter(s =>  nodes[s.id]?.lock);
  const unlockedScenes = allScenes.filter(s => !nodes[s.id]?.lock);

  let lockedOnSec = 0;
  for (const s of lockedScenes) {
    if ((nodes[s.id]?.state ?? 'off') === 'on') lockedOnSec += s.end - s.start;
  }

  const sorted         = [...unlockedScenes].sort((a, b) => (a.end - a.start) - (b.end - b.start));
  const unlockedBudget = ceiling - lockedOnSec;
  let picked           = 0;
  const selectedIds    = new Set();

  for (const scene of sorted) {
    const dur = scene.end - scene.start;
    if (picked + dur <= unlockedBudget) {
      selectedIds.add(scene.id);
      picked += dur;
    } else {
      // Over budget: pick the option closer to target_sec
      const totalWith    = lockedOnSec + picked + dur;
      const totalWithout = lockedOnSec + picked;
      if (Math.abs(totalWith - targetSec) < Math.abs(totalWithout - targetSec)) {
        selectedIds.add(scene.id);
        picked += dur;
      }
      break;
    }
  }

  const finalTotal = lockedOnSec + picked;
  const ratio      = Math.abs(finalTotal - targetSec) / targetSec;
  if (ratio > 0.1) {
    console.warn(
      `[autoCompress] 목표 ±10% 초과: 결과 ${finalTotal.toFixed(1)}s, 목표 ${targetSec}s (${(ratio * 100).toFixed(1)}%)`
    );
  }

  return unlockedScenes.map(s => ({
    id:     s.id,
    state:  selectedIds.has(s.id) ? 'on' : 'off',
    reason: selectedIds.has(s.id)
      ? '자동 압축: 목표 시간 내 포함'
      : '자동 압축: 목표 시간 초과로 제외',
  }));
}

/**
 * Returns an array of ancestor IDs from root to nodeId (inclusive).
 * e.g. ['t1', 'k1', 's1', 'sc1']
 * Returns null if not found.
 */
export function findNodePath(nodeId, treeData) {
  const roots = treeData.tree || treeData;

  function search(id, arr, path) {
    for (const node of arr) {
      const currentPath = [...path, node.id];
      if (node.id === id) return currentPath;
      if (node.children && node.children.length > 0) {
        const found = search(id, node.children, currentPath);
        if (found) return found;
      }
    }
    return null;
  }

  return search(nodeId, roots, []);
}

// 실제 서버로 S1→S3: 클립 2개 업로드 → 요청 → 분석 완료까지.
// 유료 Gemini 호출이 있으므로 E2E_REAL=1일 때만 돈다. 미리 켜 둘 것:
//   서버:  vibecut serve                       (8000번)
//   화면:  npm run dev:real -- --port 5174
// 실행:   E2E_REAL=1 E2E_CLIPS="a.mov;b.mov" npx playwright test e2e/real_s1_to_s3.spec.js
import { test, expect } from '@playwright/test';

const CLIPS = (process.env.E2E_CLIPS ?? '').split(';').filter(Boolean);
const BASE  = process.env.E2E_REAL_URL ?? 'http://localhost:5174';

test.skip(!process.env.E2E_REAL, 'E2E_REAL=1 일 때만 (실제 서버·유료 API)');

test('실제 API: 서버에서 프로젝트가 사라졌으면(서버 재시작) S1로 돌아가 안내한다', async ({ page }) => {
  await page.goto(BASE + '/');
  await page.waitForLoadState('networkidle');   // 첫 화면의 프로젝트 생성이 끝난 뒤 덮어쓴다
  await page.evaluate(() => {
    localStorage.setItem('vibecut_server_project_id', 'gone00000000');
    localStorage.setItem('vibecut_project', JSON.stringify({ status: 'analyzed', clips: [], analyzeJobId: 'x' }));
  });
  await page.goto(BASE + '/#s4');
  await page.reload();   // 해시만 바뀌면 다시 로드되지 않는다
  await expect(page.locator('text=서버가 다시 시작되어')).toBeVisible();
  await expect(page.locator('text=촬영 클립')).toBeVisible();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('vibecut_project')).status)).toBe('created');
});

test('실제 API: 클립 2개 업로드 → 분석 완료, S3에 서버 단계가 보인다', async ({ page }) => {
  test.setTimeout(15 * 60 * 1000);
  expect(CLIPS.length, 'E2E_CLIPS에 영상 2개 이상').toBeGreaterThanOrEqual(2);

  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  // proxy 404는 제외: 업로드 직후 미리보기 영상을 만드는 동안 S4가 3초마다 다시 시도한다 (의도한 동작)
  page.on('console', m => {
    if (m.type() === 'error' && !(m.location().url ?? '').includes('/proxy')) errors.push(m.text());
  });

  await page.goto(BASE + '/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  // S1: 업로드 → 클립 카드 2개
  await page.locator('input[type=file]').setInputFiles(CLIPS);
  await expect(page.locator('.clip-card:not(.add-card)')).toHaveCount(CLIPS.length, { timeout: 120_000 });
  await page.click('button:has-text("다음: 요청 →")');

  // S2: 한 줄 요청 → 확인 → 분석 시작
  // 목표 분량 위에 클립 수·전체 길이, 목표가 전체보다 길면 경고
  const info = page.locator('.card', { hasText: `클립 ${CLIPS.length}개 · 전체` });
  await expect(info).toBeVisible();
  const minutes = page.locator('input[type=number]').first();
  await minutes.fill('99');
  await expect(info).toContainText('전체 길이보다 길어요');
  await minutes.fill('0');
  await page.locator('input[type=number]').nth(1).fill('30');
  await expect(info).not.toContainText('전체 길이보다 길어요');
  await page.locator('input.fld').last().fill('시험 영상 두 개로 짧은 브이로그');
  await page.click('button:has-text("다음: 요청 확인 →")');
  await page.click('button:has-text("확정하고 분석 시작 →")');

  // S3: 서버 단계 칩이 움직이고, 끝나면 완료 문구
  await expect(page.locator('text=2. 받아쓰기·영상 분석')).toBeVisible();
  const seen = new Set();
  const deadline = Date.now() + 14 * 60 * 1000;
  while (Date.now() < deadline) {
    const running = await page.locator('.chip.on').allTextContents().catch(() => []);
    running.forEach(t => seen.add(t.trim()));
    if (await page.locator('text=분석이 완료됐어요!').isVisible()) break;
    if (await page.locator('text=분석 실패').isVisible()) {
      throw new Error('분석 실패: ' + await page.locator('.progress-wrap').innerText());
    }
    await page.waitForTimeout(1000);
  }
  await expect(page.locator('text=분석이 완료됐어요!')).toBeVisible();
  console.log('본 단계:', [...seen].join(' | '));
  console.log('하단 숫자:', (await page.locator('.bottom-bar').innerText()).replace(/\s+/g, ' '));

  // 하단 숫자가 서버 분석 결과(analysis)의 실제 값인지
  const pid = await page.evaluate(() => localStorage.getItem('vibecut_server_project_id'));
  const analysis = await (await page.request.get(`${BASE}/api/projects/${pid}/analysis`)).json();
  const stat = async (label) => (await page.locator('.stats > div', { hasText: label }).locator('.num').innerText()).trim();
  await expect.poll(() => stat('장면')).toBe(String(analysis.scenes.length));
  expect(await stat('문장')).toBe(String(analysis.lines.length));
  expect(await stat('이번 실행 비용')).toMatch(/^₩[\d,]+$/);
  // 마우스를 올리면 분석 / 목차 정리 비용이 나뉘어 보인다 (값은 전체 합)
  const costTitle = await page.locator('.stats > div', { hasText: '이번 실행 비용' }).getAttribute('title');
  console.log('비용 상세:', costTitle?.replace(/\n/g, ' | '));
  expect(costTitle).toMatch(/^분석 ₩[\d,]+/);
  expect(costTitle).toContain('목차 정리 ₩');

  // 새로고침해도 분석 완료 상태가 유지된다
  await page.reload();
  await expect(page.locator('text=분석이 완료됐어요!')).toBeVisible();

  // S4: 서버 4단 트리(GET /tree)가 밀러 컬럼에 뜬다. 모든 L1을 펼쳐 센 L4 수 = 서버 트리의 L4 수
  const tree = await (await page.request.get(`${BASE}/api/projects/${pid}/tree`)).json();
  await page.click('button:has-text("구조 편집 시작 →")');
  await expect(page.locator('.miller-col').nth(0).locator('.miller-item').first()).toBeVisible();
  let shown = 0;
  const l1 = page.locator('.miller-col').nth(0).locator('.miller-item');
  for (let a = 0; a < await l1.count(); a++) {
    await l1.nth(a).click();
    const l2 = page.locator('.miller-col').nth(1).locator('.miller-item');
    for (let b = 0; b < await l2.count(); b++) {
      await l2.nth(b).click();
      const l3 = page.locator('.miller-col').nth(2).locator('.miller-item');
      for (let c = 0; c < await l3.count(); c++) {
        await l3.nth(c).click();
        shown += await page.locator('.miller-col').nth(3).locator('.miller-item').count();
      }
    }
  }
  console.log('S4 트리:', JSON.stringify(tree.meta.counts), '화면 L4', shown);
  expect(shown).toBe(tree.meta.counts.l4);
  // 분석이 끝나면 S3가 AI 목차 정리(GET /tree?ai=true)를 하고, S4는 저장된 AI 트리를 받는다
  console.log('트리 source:', tree.meta.source, '| AI 사용량:', JSON.stringify(tree.meta.ai_usage?.tokens_by_model ?? {}));
  expect(seen.has('6. 목차 정리') || tree.meta.source === 'ai').toBe(true);
  expect(tree.meta.source).toBe('ai');

  // S4 상세 패널: L4를 고르면 그 장면 구간의 proxy 영상이 재생되고, 대사를 누르면 그 시각으로 간다
  await l1.first().click();
  await page.locator('.miller-col').nth(1).locator('.miller-item').first().click();
  await page.locator('.miller-col').nth(2).locator('.miller-item').first().click();
  await page.locator('.miller-col').nth(3).locator('.miller-item').first().click();
  const video = page.locator('.pane video');
  await expect(video).toHaveAttribute('src', new RegExp(`/api/projects/${pid}/clips/c0\\d/proxy`));
  // 업로드 직후에는 proxy를 만드는 중이라 화면이 3초마다 다시 시도한다 (최대 2분)
  await page.waitForFunction(() => { const v = document.querySelector(".pane video"); return v && v.readyState >= 2 && v.currentTime > 0.3; },
    null, { timeout: 120_000 });
  console.log('S4 영상(L4):', await video.evaluate(v => `${v.currentTime.toFixed(1)}초 / readyState ${v.readyState}`));

  // 미리보기 비율: 16:9를 누르면 영상 상자가 16:9 (가운데 기준 자르기), 원본으로 되돌림
  await page.locator('.pane .chip', { hasText: '16:9' }).click();
  await expect.poll(async () => { const b = await video.boundingBox(); return +(b.width / b.height).toFixed(2); }).toBe(1.78);
  await page.locator('.pane .chip', { hasText: '원본' }).click();

  // 상위 노드(L3)를 고르면 그 구간 첫 장면부터, 대사를 누르면 그 시각으로 가고 그 문장이 강조된다
  await page.locator('.miller-col').nth(2).locator('.miller-item').first().click();
  const lines = page.locator('.pane .log[title="누르면 이 대사로 이동"]');
  const lineCount = await lines.count();
  if (lineCount > 1) {
    const target = lines.nth(1);
    await target.click();
    await expect(target).toHaveAttribute('data-current', 'true', { timeout: 15_000 });
  }
  console.log('S4 영상(L3):', await video.evaluate(v => `${v.currentTime.toFixed(1)}초`), '| 누를 수 있는 대사', lineCount);

  // 실제 모드에는 렌더가 아직 없다: 안내만 뜨고 mock 렌더(S5)로 가지 않는다
  await page.click('button:has-text("렌더 →")');
  await expect(page.locator('.modal', { hasText: '렌더 연결은 11/22 예정' })).toBeVisible();
  await page.click('.modal button:has-text("확인")');
  await expect(page.locator('.miller')).toBeVisible();

  // AI로 목표 분량 채우기: 화면 임시 계산임을 문구로 알린다
  await page.click('button:has-text("AI로 목표 분량 채우기")');
  await expect(page.locator('text=임시 계산').first()).toBeVisible();

  // 저장된 상태가 렌더 완료여도 S5·S5-1 예시 데이터(과자 언박싱, 민수·경우, outro.mp4)는 보이지 않는다
  await page.evaluate(() => {
    const p = JSON.parse(localStorage.getItem('vibecut_project'));
    localStorage.setItem('vibecut_project', JSON.stringify({ ...p, status: 'rendered' }));
  });
  for (const screen of ['s51', 's5']) {
    await page.goto(`${BASE}/?open=${screen}#${screen}`);     // 쿼리를 바꿔 새로 연다 (해시만 바꾸면 지금 상태로 되돌아감)
    await expect(page.locator('text=렌더 연결은 11/22 예정이에요').first()).toBeVisible();
    for (const mockText of ['과자', '민수', 'outro.mp4', '편집 완료']) {
      await expect(page.locator(`text=${mockText}`)).toHaveCount(0);
    }
  }

  expect(errors, `브라우저 오류: ${errors.join(' | ')}`).toHaveLength(0);
});

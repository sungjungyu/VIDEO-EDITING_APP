import { test, expect } from '@playwright/test';

// 시연 전 전체 흐름 검증: S1 → S2 → 확인창 → S3 → S4 → S5 → S5-1
test('S1→S5-1 전체 흐름: 각 화면이 순서대로 표시된다', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });

  // 항상 S1에서 시작
  await page.addInitScript(() => localStorage.clear());
  await page.goto('/');

  // ── S1 ──────────────────────────────────────────────
  await page.waitForSelector('button:has-text("다음: 요청 →"):not([disabled])');
  await expect(page.locator('text=촬영 클립')).toBeVisible();
  await page.click('button:has-text("다음: 요청 →")');

  // ── S2 ──────────────────────────────────────────────
  await page.waitForSelector('text=기획');
  await expect(page.locator('text=목표 분량')).toBeVisible();
  await page.click('button:has-text("다음: AI가 이해한 내용 확인 →")');

  // ── 확인창 ───────────────────────────────────────────
  await page.waitForSelector('text=이렇게 이해했어요');
  await expect(page.locator('button:has-text("확정하고 분석 시작 →")')).toBeVisible();
  await page.click('button:has-text("확정하고 분석 시작 →")');

  // ── S3 ──────────────────────────────────────────────
  await page.waitForSelector('text=분석 중');
  // 분석 애니메이션 완료 대기 (최대 25초)
  await page.waitForSelector('button:has-text("구조 편집 시작 →"):not([disabled])', { timeout: 25000 });
  await expect(page.locator('text=분석이 완료됐어요!')).toBeVisible();
  await page.click('button:has-text("구조 편집 시작 →")');

  // ── S4 ──────────────────────────────────────────────
  await page.waitForSelector('.miller', { timeout: 5000 });
  await expect(page.locator('.miller')).toBeVisible();
  // 첫 번째 컬럼에 항목이 있는지 확인
  await expect(page.locator('.miller-col').first()).toBeVisible();
  await page.click('button:has-text("렌더 →")');

  // ── S5 ──────────────────────────────────────────────
  await page.waitForSelector('text=편집 중');
  // 렌더 애니메이션 완료 대기 (최대 15초)
  await page.waitForSelector('button:has-text("결과 보기 →"):not([disabled])', { timeout: 15000 });
  await expect(page.locator('text=렌더가 완료됐어요!')).toBeVisible();
  await page.click('button:has-text("결과 보기 →")');

  // ── S5-1 ─────────────────────────────────────────────
  // ResultView: TopBar에 "편집 완료" + "내보내기 ↓" 버튼
  await page.waitForSelector('text=편집 완료', { timeout: 5000 });
  await expect(page.locator('button:has-text("내보내기")')).toBeVisible();

  // 오류 없어야 함
  expect(errors, `브라우저 오류: ${errors.join(' | ')}`).toHaveLength(0);
});

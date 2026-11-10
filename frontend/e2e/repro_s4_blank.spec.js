import { test, expect } from '@playwright/test';

// S1 → S2 → 확인창 → S3 완료 → S4 흰 화면 재현
// 이 테스트는 버그가 있을 때 콘솔 오류를 기록하고,
// 버그가 고쳐진 뒤에는 S4 콘텐츠(.miller)가 보이는지 검증한다.
test('S1→S2→확인창→S3→S4: 콘솔 오류 없이 MillerColumns가 표시된다', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });

  // localStorage 비워서 항상 S1에서 시작
  await page.addInitScript(() => localStorage.clear());
  await page.goto('/');

  // S1: 클립이 로드되면 "다음: 요청 →" 버튼 활성화
  await page.waitForSelector('button:has-text("다음: 요청 →"):not([disabled])');
  await page.click('button:has-text("다음: 요청 →")');

  // S2: "다음: AI가 이해한 내용 확인 →" 클릭
  await page.waitForSelector('button:has-text("다음: AI가 이해한 내용 확인 →")');
  await page.click('button:has-text("다음: AI가 이해한 내용 확인 →")');

  // 확인창: "확정하고 분석 시작 →" 클릭
  await page.waitForSelector('button:has-text("확정하고 분석 시작 →")');
  await page.click('button:has-text("확정하고 분석 시작 →")');

  // S3: 분석 애니메이션 완료까지 대기 (최대 25초)
  await page.waitForSelector('button:has-text("구조 편집 시작 →"):not([disabled])', { timeout: 25000 });
  await page.click('button:has-text("구조 편집 시작 →")');

  // S4: MillerColumns(.miller)가 표시돼야 한다
  await page.waitForSelector('.miller', { timeout: 5000 });

  // 콘솔 오류 출력 (CI 로그 확인용)
  if (errors.length > 0) {
    console.log('=== 브라우저 콘솔 오류 ===');
    errors.forEach((e) => console.log(e));
  }

  expect(errors, '브라우저 오류가 없어야 합니다').toHaveLength(0);
  await expect(page.locator('.miller')).toBeVisible();
});

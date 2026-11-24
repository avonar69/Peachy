import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import type { Browser } from 'playwright-core';
import { launch, VIEWPORTS } from './harness.ts';
import { openItemPage } from './item-fixture.ts';

describe('作品排序触控菜单', () => {
  let browser: Browser;
  before(async () => { browser = await launch() });
  after(async () => { await browser?.close() });
  for (const viewport of VIEWPORTS) it(`${viewport.name} 名称排序菜单可选择`, { timeout: 60000 }, async () => {
    const opened = await openItemPage(browser, '/', viewport, { ready: '#grid [data-media-card]' });
    const { page } = opened;
    try {
      const trigger = page.locator('[data-video-sort] [aria-haspopup="listbox"]').first();
      await trigger.scrollIntoViewIfNeeded();
      if (viewport.mobile) await trigger.tap(); else await trigger.click();
      const option = page.getByRole('option', { name: '名称', exact: true });
      try { await option.waitFor({ timeout: 3000 }) }
      catch {
        assert.fail(JSON.stringify(await trigger.evaluate(node => ({
          trigger: node.outerHTML, menus: [...document.querySelectorAll('[role="listbox"]')].map(menu => menu.outerHTML),
          focus: document.activeElement?.outerHTML,
        }))));
      }
      if (viewport.mobile) await option.tap(); else await option.click();
      await page.waitForURL(url => url.searchParams.get('sort') === 'name');
      assert.deepEqual(opened.problems.filter(problem => !problem.includes('VIDEOJS')), []);
    } finally { await opened.close() }
  });
});

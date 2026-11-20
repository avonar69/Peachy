import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import type { Browser } from 'playwright-core';
import { launch, layout, VIEWPORTS, visit } from './harness.ts';

describe('文件夹跨页资料编辑', () => {
  let browser: Browser;
  before(async () => { browser = await launch() });
  after(async () => { await browser?.close() });
  for (const viewport of VIEWPORTS) it(`${viewport.name} 全选目录并在任务浮层保存`, { timeout: 90_000 }, async () => {
    const opened = await visit(browser, '/?browse=folders&loc=local', viewport);
    const { page } = opened;
    try {
      const roots = await (await page.request.get(new URL('/api/folders?loc=local', page.url()).toString())).json();
      const folder = roots.roots[0];
      const entries = Array.from({ length: 45 }, (_, index) => ({ id: 9100 + index, name: `Example ${index}.mp4`, medium: 'video', location: 'local' }));
      await page.route('**/api/items?*', route => {
        const params = new URL(route.request().url()).searchParams;
        const offset = Number(params.get('offset') || 0), limit = Number(params.get('limit') || 20);
        return route.fulfill({ json: { items: entries.slice(offset, offset + limit), total: entries.length } });
      });
      await page.route('**/api/folders/selection?*', route => route.fulfill({ json: { ids: entries.map(item => item.id), total: 45 } }));
      let completed = false;
      let submitted: { kind: string; payload: { ids: number[]; name: string } } | undefined;
      await page.route('**/api/metadata-job', async route => {
        if (route.request().method() === 'POST') submitted = route.request().postDataJSON();
        await route.fulfill({ json: { job_id: 'bulk-folder', status: completed ? 'complete' : 'running', checked: completed ? 45 : 0, total: 45 } });
      });
      await page.goto(new URL(`/?browse=folders&loc=local&folder=${folder.id}`, page.url()).toString());
      await page.getByRole('radiogroup', { name: '馆藏显示方式' }).locator('label')
        .filter({ has: page.getByRole('radio', { name: '列表', exact: true }) }).click();
      await page.locator('[data-catalog-row]').first().waitFor();
      await page.locator('label').filter({ has: page.getByRole('checkbox', { name: '全选本页作品', exact: true }) }).click();
      await page.getByRole('button', { name: '选择文件夹中的全部作品', exact: true }).click();
      await page.locator('[data-batch-action="studio"]').click();
      const dialog = page.locator('dialog[open]').last();
      await dialog.locator('input[name="metadata-name"]').fill('Folder Studio');
      await dialog.locator('[data-modal-confirm]').click();
      await dialog.waitFor({ state: 'hidden' });
      const popup = page.locator('[data-processing-dock][aria-label="保存资料"]');
      await popup.getByText('正在应用编辑').waitFor();
      assert.equal(submitted?.kind, 'batch');
      assert.equal(submitted?.payload.ids.length, 45);
      assert.equal(submitted?.payload.name, 'Folder Studio');
      assert.ok((await layout(page)).scrollWidth <= viewport.width + 1);
      completed = true;
      await popup.getByText('资料已保存').waitFor();
      await popup.getByRole('button', { name: '关闭', exact: true }).click();
      await popup.waitFor({ state: 'hidden' });
      assert.deepEqual(opened.problems.filter(problem => problem.startsWith('pageerror')), []);
    } finally { await opened.close() }
  });
});

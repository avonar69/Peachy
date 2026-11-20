import { act } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { startMetadataEdit } from '../../src/react/components/metadata-edit-progress';
import { buttonNamed, click, mount, pending } from './render';

const sonner = vi.hoisted(() => ({ custom: vi.fn(), dismiss: vi.fn() }));
vi.mock('sonner', () => ({ toast: sonner }));
beforeEach(() => { sessionStorage.clear(); localStorage.setItem('peach.language', 'en'); sonner.custom.mockClear(); sonner.dismiss.mockClear() });

it('保存期间显示实际计数，失败后可重试和关闭', async () => {
  const response = pending<Response>();
  const posts: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { posts.push(JSON.parse(String(init.body))); return posts.length === 1 ? response.answer
      : new Response(JSON.stringify({ job_id: 'bulk-edit', status: 'running', total: 252, checked: 0 })); }
    return new Response(JSON.stringify({ job_id: 'bulk-edit', status: 'failed', checked: 200, total: 252, error: 'Remaining batch failed' }));
  }));
  const saved = vi.fn();
  let saving!: Promise<void>;
  await act(async () => { saving = startMetadataEdit('batch', { ids: [1, 2], operation: 'actor', name: 'Jane Doe' }, saved) });
  const [renderRunning] = sonner.custom.mock.calls.at(-1)!;
  const running = await mount(renderRunning());
  expect(running.querySelector('progress')?.max).toBe(2);
  expect(buttonNamed('Close', running)).toBeNull();
  await response.release(new Response(JSON.stringify({ job_id: 'bulk-edit', status: 'running', checked: 0, total: 252 })));
  await act(async () => { await saving });
  const [renderFailure] = sonner.custom.mock.calls.at(-1)!;
  const failed = await mount(renderFailure());
  expect(failed.textContent).toContain('200 / 252');
  expect(failed.textContent).toContain('Remaining batch failed');
  expect(saved).not.toHaveBeenCalled();
  await click(buttonNamed('Retry', failed));
  expect(posts).toHaveLength(2);
  expect(posts[0]).toEqual(posts[1]);
  await click(buttonNamed('Close', failed));
  expect(sonner.dismiss).toHaveBeenCalledWith('peach-metadata-edit-progress');
});

import { act } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { MetadataEditRecovery, startMetadataEdit } from '../../src/react/components/metadata-edit-progress';
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
  expect(sonner.dismiss).toHaveBeenCalledWith(expect.stringMatching(/^peach-metadata-edit-progress-/));
});

it('多个编辑分别跟踪排队状态、完成回执与浏览器恢复记录', async () => {
  const first = pending<Response>(), second = pending<Response>();
  let submitted = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      submitted++;
      return new Response(JSON.stringify({ job_id: submitted === 1 ? 'first-edit' : 'second-edit',
        status: submitted === 1 ? 'running' : 'queued', name: submitted === 1 ? 'Studio A' : 'Actor B',
        total: 1, queue_position: submitted === 1 ? undefined : 1 }));
    }
    return url.includes('first-edit') ? first.answer : second.answer;
  }));
  const savedFirst = vi.fn(), savedSecond = vi.fn();
  await act(async () => { await startMetadataEdit('batch', { ids: [1], operation: 'studio', name: 'Studio A' }, savedFirst) });
  const firstToastId = sonner.custom.mock.calls.at(-1)![1].id;
  await act(async () => { await startMetadataEdit('batch', { ids: [2], operation: 'actor', name: 'Actor B' }, savedSecond) });
  const [renderQueued, options] = sonner.custom.mock.calls.at(-1)!;
  expect(options.id).not.toBe(firstToastId);
  expect(Object.keys(JSON.parse(sessionStorage.getItem('peach-metadata-edit')!))).toEqual(['first-edit', 'second-edit']);
  const queued = await mount(renderQueued());
  expect(queued.textContent).toContain('Actor B');
  expect(queued.textContent).toContain('Waiting in queue');
  expect(buttonNamed('Close', queued)).toBeNull();
  await first.release(new Response(JSON.stringify({ job_id: 'first-edit', status: 'complete', result: { changed: 1 } })));
  expect(savedFirst).toHaveBeenCalledWith({ changed: 1 });
  expect(savedSecond).not.toHaveBeenCalled();
  expect(Object.keys(JSON.parse(sessionStorage.getItem('peach-metadata-edit')!))).toEqual(['second-edit']);
  const [renderCompleted] = sonner.custom.mock.calls.at(-1)!;
  const completed = await mount(renderCompleted());
  await click(buttonNamed('Close', completed));
  expect(Object.keys(JSON.parse(sessionStorage.getItem('peach-metadata-edit')!))).toEqual(['second-edit']);
  await second.release(new Response(JSON.stringify({ job_id: 'second-edit', status: 'complete', result: { changed: 2 } })));
  expect(savedSecond).toHaveBeenCalledWith({ changed: 2 });
  expect(sessionStorage.getItem('peach-metadata-edit')).toBeNull();
});

it('刷新后为每个排队编辑恢复独立通知', async () => {
  sessionStorage.setItem('peach-metadata-edit', JSON.stringify({ 'edit-a': 'toast-a', 'edit-b': 'toast-b' }));
  const fetch = vi.fn(async (url: string) => new Response(JSON.stringify({ job_id: new URL(url, 'http://localhost').searchParams.get('job_id'), status: 'complete' })));
  vi.stubGlobal('fetch', fetch);
  await mount(<MetadataEditRecovery />);
  expect(sonner.custom.mock.calls.map(call => call[1].id)).toEqual(expect.arrayContaining(['toast-a', 'toast-b']));
  expect(sessionStorage.getItem('peach-metadata-edit')).toBeNull();
});

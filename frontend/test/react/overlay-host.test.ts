import { expect, it, vi } from 'vitest';
import { followModalLayer } from '../../src/react/components/overlay-host';

it('通知栈跟随原生模态层并在关闭后返回页面', async () => {
  const host = document.createElement('div');
  const stage = document.createElement('dialog');
  const edit = document.createElement('dialog');
  document.body.append(host, stage, edit);
  const restore = followModalLayer(host);
  try {
    stage.open = true;
    await vi.waitFor(() => expect(host.parentElement).toBe(stage));
    edit.open = true;
    await vi.waitFor(() => expect(host.parentElement).toBe(edit));
    edit.remove();
    await vi.waitFor(() => expect(host.parentElement).toBe(stage));
    stage.open = false;
    await vi.waitFor(() => expect(host.parentElement).toBe(document.body));
  } finally { restore(); host.remove(); stage.remove(); edit.remove(); }
});

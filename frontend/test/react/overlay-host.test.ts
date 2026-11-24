import { expect, it, vi } from 'vitest';
import { followModalLayer } from '../../src/react/components/overlay-host';

it('通知栈跟随原生模态层并在关闭后返回页面', async () => {
  const host = document.createElement('div');
  const stage = document.createElement('dialog');
  stage.id = 'stage';
  const edit = document.createElement('dialog');
  document.body.append(host, stage, edit);
  const restore = followModalLayer(host);
  try {
    stage.open = true;
    await vi.waitFor(() => expect(host.parentElement).toBe(stage));
    expect(host.hidden).toBe(false);
    edit.open = true;
    await vi.waitFor(() => expect(host.parentElement).toBe(edit));
    expect(host.hidden).toBe(true);
    edit.remove();
    await vi.waitFor(() => expect(host.parentElement).toBe(stage));
    expect(host.hidden).toBe(false);
    stage.open = false;
    await vi.waitFor(() => expect(host.parentElement).toBe(document.body));
  } finally { restore(); host.remove(); stage.remove(); edit.remove(); }
});

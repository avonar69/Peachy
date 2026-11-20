import { useEffect, useState } from 'react';
import { RiEditLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/base/buttons/button';
import { ApiError, apiGet, apiSend, errorMessage } from '../../api';
import { formatTranslation } from '../../i18n';
import { watchJob, type JobState } from '../../jobs';
import { pageOpens, writeShell } from '@peach/shell';
import { queryClient } from '../query';
import { TaskPopup } from './task-popup';

interface EditState extends JobState { result?: Record<string, unknown>; queue_position?: number; name?: string; operation?: string }
const KEY = 'peach-metadata-edit';
const URL = '/api/metadata-job';
const ID = 'peach-metadata-edit-progress';

function tracked(): Record<string, string> {
  const value = sessionStorage.getItem(KEY);
  if (!value) return {};
  try { const parsed = JSON.parse(value); return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}; }
  catch { return { [value]: `${ID}-${value}` }; }
}

function forget(id?: string) {
  if (!id) return;
  const ids = tracked(); delete ids[id];
  if (Object.keys(ids).length) sessionStorage.setItem(KEY, JSON.stringify(ids)); else sessionStorage.removeItem(KEY);
}

function Panel({ state, displayId, retry }: { state: EditState; displayId: string; retry?: () => void }) {
  const [expanded, setExpanded] = useState(true);
  useEffect(() => setExpanded(state.status !== 'queued'), [state.status]);
  const active = state.status === 'running' || state.status === 'queued';
  return <div className="peach-react" data-metadata-edit={state.job_id || displayId}><TaskPopup label="保存资料" title="保存资料" expanded={expanded}
    subtitle={state.name ? <p className="wrap-anywhere text-caption-1-regular text-text-secondary" data-i18n-ignore>{state.name}</p> : undefined}
    toggle={() => setExpanded(value => !value)} measure tone={state.status === 'failed' ? 'error' : 'neutral'}
    icon={<RiEditLine aria-hidden className="size-5 shrink-0" />}
    footer={active ? <span>{state.status === 'queued' ? '等待应用编辑' : '正在应用编辑'}</span> : <>
      {state.status === 'failed' && retry ? <Button size="small" variant="secondary" onClick={retry}>重试</Button> : null}
      <Button size="small" variant="secondary" onClick={() => { forget(state.job_id); toast.dismiss(displayId) }}>关闭</Button>
    </>}>
    {state.status === 'queued' ? <p>{formatTranslation('排队位置：{0}', String(state.queue_position || 1))}</p>
      : state.status === 'failed' ? <><p>{state.checked || 0} / {state.total || 1}</p><p className="wrap-anywhere">{state.error}</p></> : state.status === 'complete' ? <p>资料已保存</p>
      : state.status === 'cancelled' ? <p>已取消</p> : <>
      {state.error ? <p>{state.error}</p> : null}<p>{state.checked || 0} / {state.total || 1}</p>
      <progress aria-label="资料保存进度" value={state.checked || 0} max={state.total || 1} />
    </>}
  </TaskPopup></div>;
}

function show(state: EditState, displayId: string, retry?: () => void) {
  toast.custom(() => <Panel state={state} displayId={displayId} retry={retry} />, { id: displayId, toasterId: 'processing',
    className: 'processing-task-toast', duration: state.status === 'complete' ? 6000 : Infinity, dismissible: false });
}

async function follow(initial: EditState, displayId: string, saved?: (result: Record<string, unknown>) => void, retry?: () => void) {
  const id = initial.job_id;
  if (!id) { show({ status: 'failed', error: '任务状态已失效，请重新发起任务' }, displayId); return; }
  sessionStorage.setItem(KEY, JSON.stringify({ ...tracked(), [id]: displayId }));
  let terminal = false;
  await watchJob({ active: () => !terminal && tracked()[id] === displayId, keepWatching: true,
    read: async signal => {
      try { return await apiGet<EditState>(`${URL}?job_id=${encodeURIComponent(id)}`, signal); }
      catch (error) {
        if (error instanceof ApiError && [400, 404].includes(error.status)) return { ...initial, status: 'failed', error: errorMessage(error) };
        throw error;
      }
    },
    render: state => {
      if (state.job_id !== id) { terminal = true; forget(id); show({ status: 'failed', error: '任务状态已失效，请重新发起任务' }, displayId); return; }
      show(state, displayId, retry);
      if (state.status === 'running' || state.status === 'queued') return;
      terminal = true;
      forget(id);
      if (state.status === 'complete') {
        void queryClient.invalidateQueries();
        writeShell({ pageOpens: pageOpens + 1 });
        saved?.(state.result || {});
      }
    }, disconnected: () => show({ ...initial, error: '暂时无法读取进度，正在重新连接…' }, displayId) });
}

/** 保存交给服务端，弹层关闭与任务生命周期互不依赖。 */
export async function startMetadataEdit(kind: 'batch' | 'folder' | 'scene', payload: object,
  saved?: (result: Record<string, unknown>) => void): Promise<void> {
  const ids = (payload as { ids?: number[] }).ids;
  const displayId = `${ID}-${crypto.randomUUID()}`;
  let jobId: string | undefined;
  show({ status: 'running', checked: 0, total: ids?.length || 1 }, displayId);
  const retry = () => { forget(jobId); toast.dismiss(displayId); void startMetadataEdit(kind, payload, saved) };
  try {
    const state = await apiSend<EditState>(URL, { kind, payload });
    if (!state?.job_id) throw new Error('任务状态已失效，请重新发起任务');
    jobId = state.job_id;
    show(state, displayId, retry);
    void follow(state, displayId, saved, retry);
  } catch (error) { show({ status: 'failed', error: errorMessage(error) }, displayId, retry); }
}

export function MetadataEditRecovery() {
  useEffect(() => {
    for (const [id, displayId] of Object.entries(tracked())) {
      void apiGet<EditState>(`${URL}?job_id=${encodeURIComponent(id)}`).then(state => {
        if (state.job_id === id) return follow(state, displayId);
        forget(id);
        show({ status: 'failed', error: '任务状态已失效，请重新发起任务' }, displayId);
      }).catch(error => { forget(id); show({ status: 'failed', error: errorMessage(error) }, displayId) });
    }
  }, []);
  return null;
}

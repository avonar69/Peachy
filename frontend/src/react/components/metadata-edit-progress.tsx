import { useEffect, useState } from 'react';
import { RiEditLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/base/buttons/button';
import { apiGet, apiSend, errorMessage } from '../../api';
import { watchJob, type JobState } from '../../jobs';
import { pageOpens, writeShell } from '@peach/shell';
import { queryClient } from '../query';
import { TaskPopup } from './task-popup';

interface EditState extends JobState { result?: Record<string, unknown> }
const KEY = 'peach-metadata-edit';
const URL = '/api/metadata-job';
const ID = 'peach-metadata-edit-progress';

function Panel({ state, retry }: { state: EditState; retry?: () => void }) {
  const [expanded, setExpanded] = useState(true);
  return <div className="peach-react"><TaskPopup label="保存资料" title="保存资料" expanded={expanded}
    toggle={() => setExpanded(value => !value)} measure tone={state.status === 'failed' ? 'error' : 'neutral'}
    icon={<RiEditLine aria-hidden className="size-5 shrink-0" />}
    footer={state.status === 'running' ? <span>正在应用编辑</span> : <>
      {state.status === 'failed' && retry ? <Button size="small" variant="secondary" onClick={retry}>重试</Button> : null}
      <Button size="small" variant="secondary" onClick={() => { sessionStorage.removeItem(KEY); toast.dismiss(ID) }}>关闭</Button>
    </>}>
    {state.status === 'failed' ? <><p>{state.checked || 0} / {state.total || 1}</p><p className="wrap-anywhere">{state.error}</p></> : state.status === 'complete' ? <p>资料已保存</p> : <>
      {state.error ? <p>{state.error}</p> : null}<p>{state.checked || 0} / {state.total || 1}</p>
      <progress aria-label="资料保存进度" value={state.checked || 0} max={state.total || 1} />
    </>}
  </TaskPopup></div>;
}

function show(state: EditState, retry?: () => void) {
  toast.custom(() => <Panel state={state} retry={retry} />, { id: ID, toasterId: 'processing',
    className: 'processing-task-toast', duration: state.status === 'complete' ? 6000 : Infinity, dismissible: false });
}

async function follow(initial: EditState, saved?: (result: Record<string, unknown>) => void, retry?: () => void) {
  const id = initial.job_id;
  if (!id) { show({ status: 'failed', error: '任务状态已失效，请重新发起任务' }); return; }
  sessionStorage.setItem(KEY, id);
  let terminal = false;
  await watchJob({ active: () => !terminal && sessionStorage.getItem(KEY) === id,
    read: signal => apiGet<EditState>(URL, signal),
    render: state => {
      if (state.job_id !== id) { terminal = true; show({ status: 'failed', error: '任务状态已失效，请重新发起任务' }); return; }
      show(state, retry);
      if (state.status === 'running') return;
      terminal = true;
      sessionStorage.removeItem(KEY);
      if (state.status === 'complete') {
        void queryClient.invalidateQueries();
        writeShell({ pageOpens: pageOpens + 1 });
        saved?.(state.result || {});
      }
    }, disconnected: () => show({ ...initial, error: '暂时无法读取进度，正在重新连接…' }) });
}

/** 保存交给服务端，弹层关闭与任务生命周期互不依赖。 */
export async function startMetadataEdit(kind: 'batch' | 'folder' | 'scene', payload: object,
  saved?: (result: Record<string, unknown>) => void): Promise<void> {
  const ids = (payload as { ids?: number[] }).ids;
  show({ status: 'running', checked: 0, total: ids?.length || 1 });
  const retry = () => { void startMetadataEdit(kind, payload, saved) };
  try {
    const state = await apiSend<EditState>(URL, { kind, payload });
    if (!state?.job_id) throw new Error('任务状态已失效，请重新发起任务');
    show(state, retry);
    void follow(state, saved, retry);
  } catch (error) { show({ status: 'failed', error: errorMessage(error) }, retry); }
}

export function MetadataEditRecovery() {
  useEffect(() => {
    const tracked = sessionStorage.getItem(KEY);
    if (tracked) void apiGet<EditState>(URL).then(state => {
      if (state.job_id === tracked) return follow(state);
      sessionStorage.removeItem(KEY);
      show({ status: 'failed', error: '任务状态已失效，请重新发起任务' });
    }).catch(error => show({ status: 'failed', error: errorMessage(error) }));
  }, []);
  return null;
}

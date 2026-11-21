"""手工资料保存使用固定作品集合与服务端后台任务。"""
import copy
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor


class MetadataEditQueue:
    """按提交顺序串行执行资料保存，每项保留独立进度与终态。"""

    def __init__(self, job):
        self.job = job
        self.lock = threading.RLock()
        self.entries = OrderedDict()
        self.futures = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='PeachMetadataQueue')
        self.closed = False

    def submit(self, work, initial):
        with self.lock:
            if self.closed:
                raise ValueError('资料保存队列已关闭')
            if sum(row['status'] == 'queued' for row in self.entries.values()) >= 100:
                raise ValueError('资料保存队列已满，请稍后再试')
            terminal = [key for key, row in self.entries.items() if row['status'] in ('complete', 'failed', 'cancelled')]
            for key in terminal[:-99]:
                self.entries.pop(key)
                self.futures.pop(key, None)
            key = uuid.uuid4().hex
            self.entries[key] = {**initial, 'job_id': key, 'status': 'queued', 'checked': 0, 'error': ''}
            self.futures[key] = self.executor.submit(self._execute, key, work)
            return self.snapshot(key)

    def _execute(self, key, work):
        with self.lock:
            if self.closed:
                self.entries[key]['status'] = 'cancelled'
                return
            self.entries[key]['status'] = 'running'
            initial = {k: v for k, v in self.entries[key].items() if k != 'job_id'}
        try:
            state = self.job.start(work, restart=True, initial=initial)
            with self.lock:
                self.entries[key]['native_id'] = state['job_id']
            self.job.thread.join()
            state = self.job.snapshot()
        except Exception as error:
            state = {'status': 'failed', 'error': str(error)}
        with self.lock:
            self.entries[key].update({k: v for k, v in state.items() if k != 'job_id'})

    def snapshot(self, key=None):
        with self.lock:
            current = self.job.snapshot() or {}
            rows = []
            position = 0
            for identifier, entry in self.entries.items():
                row = copy.deepcopy(entry)
                if row['status'] == 'running' and row.get('native_id') == current.get('job_id'):
                    row.update({k: v for k, v in current.items() if k != 'job_id'})
                row.pop('native_id', None)
                if row['status'] == 'queued':
                    position += 1
                    row['queue_position'] = position
                if identifier == key:
                    return row
                rows.append(row)
            if key:
                raise ValueError('资料保存任务不存在')
            return {'status': 'running' if any(row['status'] in ('running', 'queued') for row in rows) else 'idle', 'jobs': rows}

    def close(self):
        with self.lock:
            self.closed = True
            for row in self.entries.values():
                if row['status'] == 'queued':
                    row['status'] = 'cancelled'
        self.executor.shutdown(wait=True, cancel_futures=True)


def q_metadata_job(contract, args):
    return contract.metadata_queue.snapshot(args.get('job_id'))


def w_metadata_job(contract, body):
    from .web_batch import w_batch
    from .web_folders import w_folder_rule
    from .web_scene_metadata import w_scene_metadata

    kind = body.get('kind')
    handlers = {'batch': w_batch, 'folder': w_folder_rule, 'scene': w_scene_metadata}
    if kind not in handlers or not isinstance(body.get('payload'), dict):
        raise ValueError('资料保存请求无效')
    payload = copy.deepcopy(body['payload'])
    if kind == 'batch':
        ids = payload.get('ids')
        if (not isinstance(ids, list) or not ids or len(ids) > 100000
                or any(type(value) is not int or value < 1 for value in ids)
                or payload.get('operation') not in ('studio', 'actor')):
            raise ValueError('请选择作品与资料操作')
        ids = list(dict.fromkeys(ids))
        groups = [ids[start:start + 200] for start in range(0, len(ids), 200)]
    else:
        groups = [None]
    job = contract.metadata_job

    def work(job_id):
        done = 0
        for group in groups:
            result = handlers[kind](contract, {**payload, **({'ids': group} if group else {})})
            done += len(group) if group else 1
            job.update(job_id, checked=done, result=result)
        job.update(job_id, status='complete')

    return contract.metadata_queue.submit(work, {'total': len(ids) if kind == 'batch' else 1, 'kind': kind,
        'operation': payload.get('operation', ''), 'name': payload.get('name', '') if isinstance(payload.get('name', ''), str) else ''})

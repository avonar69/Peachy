"""手工资料保存使用固定作品集合与服务端后台任务。"""
import copy
import uuid

from .jobs import JobAlreadyRunning


def q_metadata_job(contract, args):
    return contract.metadata_job.snapshot() or {'status': 'idle'}


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
    token = uuid.uuid4().hex
    job = contract.metadata_job

    def work(job_id):
        done = 0
        for group in groups:
            result = handlers[kind](contract, {**payload, **({'ids': group} if group else {})})
            done += len(group) if group else 1
            job.update(job_id, checked=done, result=result)
        job.update(job_id, status='complete')

    state = job.start(work, restart=True, initial={'request_token': token, 'checked': 0,
        'total': len(ids) if kind == 'batch' else 1, 'kind': kind})
    if state.get('request_token') != token:
        raise JobAlreadyRunning('资料保存任务正在运行，请完成后再保存')
    return state

"""原目录的来源边界、目录规则预览、撤回与扫描继承。"""
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from peach import folder_rules, media_folders, scan, web_folders, web_metadata_jobs
from peach.entities import upsert_asset_entity
from peach.field_owners import write_owned_fields
from peach.migrations import upgrade
from peach.web_catalog import q_items
from peach.web_state import WebContract

ROOT = Path(__file__).resolve().parents[1]


class MediaFolderTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / 'ledger.db'
        upgrade(self.path, ROOT / 'migrations')
        self.contract = WebContract(self.path, candidate_root=self.root / 'generated',
                                    follow_state_root=self.root / 'state', snapshot_root=self.root / 'snapshots')
        self.addCleanup(self.contract.metadata_queue.close)
        self.config = SimpleNamespace(locations={'local': ('R:\\Media',), '115': ('A:\\收藏',)},
                                      library_names={}, library_icons={})
        self.addCleanup(patch.stopall)
        patch('peach.web_folders.settings_file.active', return_value=self.config).start()
        self.rows = [('local', 'R:\\Media\\精选\\作者甲\\a.mp4'),
                     ('local', 'R:\\Media\\精选\\作者甲\\视频\\b.mp4'),
                     ('local', 'R:\\Media\\精选\\作者甲2\\c.mp4'),
                     ('115', 'A:\\收藏\\精选\\d.mp4')]
        with self.contract.write_transaction() as connection:
            connection.executemany("INSERT INTO asset(location,path,name,medium) VALUES(?,?,?,'video')",
                                   [(loc, path, path.rsplit('\\', 1)[1]) for loc, path in self.rows])

    def key(self, path='R:\\Media\\精选\\作者甲', location='local'):
        return media_folders.folder_id(location, path)

    def read(self, **args):
        return web_folders.q_folders(self.contract, args)

    def edit_result(self, state):
        self.contract.metadata_queue.futures[state['job_id']].result(timeout=20)
        return web_metadata_jobs.q_metadata_job(self.contract, {'job_id': state['job_id']})

    def rule(self, **extra):
        return {'folder': self.key(), 'purpose': 'creator', 'name': '作者甲',
                'recursive': True, 'future': False, **extra}

    def save(self, **extra):
        body = self.rule(**extra)
        preview = web_folders.w_folder_preview(self.contract, body)
        revision = self.read()['rules_revision']
        result = web_folders.w_folder_rule(self.contract, {**body, 'action': 'save',
                     'plan_version': preview['plan_version'], 'expected_revision': revision})
        return result

    def test_tree_keeps_personal_names_and_separate_source_roots(self):
        result = self.read(folder=self.key())
        self.assertEqual([row['name'] for row in result['ancestors']], ['Media', '精选', '作者甲'])
        self.assertEqual([row['name'] for row in result['children']], ['视频'])
        self.assertEqual(result['selected']['videos'], 2)
        self.assertEqual(len(result['roots']), 2)
        self.assertEqual(len(self.read(loc='115')['roots']), 1)
        self.assertEqual(self.read(library='不存在')['roots'], [])

    def test_path_scope_is_case_insensitive_and_observes_component_boundary(self):
        with self.contract.read_connection() as connection:
            clause, args = media_folders.path_predicate('local', 'r:\\media\\精选\\作者甲')
            self.assertEqual([row[0] for row in connection.execute('SELECT id FROM asset a WHERE ' + clause, args)], [1, 2])
            clause, args = media_folders.path_predicate('local', 'R:\\Media\\精选\\作者甲', False)
            self.assertEqual([row[0] for row in connection.execute('SELECT id FROM asset a WHERE ' + clause, args)], [1])
        patch('peach.web_catalog.settings_file.active', return_value=self.config).start()
        self.assertEqual(sorted(row['id'] for row in q_items(self.contract, {'folder': self.key()})['items']), [1, 2])
        self.assertEqual(q_items(self.contract, {'folder': 'missing'})['total'], 0)

    def test_sql_wildcard_directory_names_are_literal(self):
        with self.contract.write_transaction() as connection:
            connection.execute("INSERT INTO asset(location,path,name,medium) VALUES('local',?,'e.mp4','video')",
                               ('R:\\Media\\100%_test\\e.mp4',))
            clause, args = media_folders.path_predicate('local', 'R:\\Media\\100%_test')
            self.assertEqual(connection.execute('SELECT count(*) FROM asset a WHERE ' + clause, args).fetchone()[0], 1)

    def test_category_rule_keeps_classification_without_creating_identity(self):
        self.save(purpose='category', name='')
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM asset_entity').fetchone()[0], 0)
        self.assertEqual(self.read(folder=self.key())['rule']['purpose'], 'category')

    def test_selection_covers_all_folder_pages_with_path_and_source_boundaries(self):
        with self.contract.write_transaction() as connection:
            connection.executemany("INSERT INTO asset(location,path,name,medium) VALUES('local',?,?,'video')",
                [(f'R:\\Media\\精选\\作者甲\\{i}.mp4', f'{i}.mp4') for i in range(250)])
            connection.execute("INSERT INTO asset(location,path,name,medium,disposal) VALUES('local',?,'trash.mp4','video','trash')",
                ('R:\\Media\\精选\\作者甲\\trash.mp4',))
        result = web_folders.q_folder_selection(self.contract, {'folder': self.key()})
        self.assertEqual(result['total'], 252)
        self.assertNotIn(3, result['ids'])
        self.assertNotIn(4, result['ids'])
        direct = web_folders.q_folder_selection(self.contract, {'folder': self.key(), 'folder_recursive': '0'})
        self.assertEqual(direct['total'], 251)
        with self.assertRaises(ValueError):
            web_folders.q_folder_selection(self.contract, {'folder': 'missing'})

    def test_directory_metadata_applies_to_existing_and_future_items_and_withdraws(self):
        extra = {'studio': 'Studio One', 'series': 'Series One', 'performers': ['Jane Doe', 'Clara Fargo']}
        self.save(purpose='category', name='', future=True, assignments=extra)
        with self.contract.write_transaction() as connection:
            connection.execute("INSERT INTO asset(location,path,name,medium) VALUES('local',?,'new.mp4','video')",
                ('R:\\Media\\精选\\作者甲\\视频\\new.mp4',))
            self.assertEqual(folder_rules.apply_new(connection, [5]), 1)
            self.assertEqual(connection.execute('SELECT studio,series FROM asset WHERE id=5').fetchone()[:], ('Studio One', 'Series One'))
            names = {row[0] for row in connection.execute('SELECT e.canonical_name FROM entity e JOIN asset_entity ae ON ae.entity_id=e.id WHERE ae.asset_id=5')}
            self.assertTrue({'Jane Doe', 'Clara Fargo', 'Studio One', 'Series One'} <= names)
            self.assertEqual(folder_rules.apply_new(connection, [5]), 0)
        revision = self.read()['rules_revision']
        web_folders.w_folder_rule(self.contract, {'folder': self.key(), 'action': 'remove', 'expected_revision': revision})
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM asset_entity').fetchone()[0], 0)
            self.assertFalse(connection.execute('SELECT studio FROM asset WHERE id=5').fetchone()[0])

    def test_directory_actor_assignment_preserves_other_cast(self):
        with self.contract.write_transaction() as connection:
            upsert_asset_entity(connection, kind='performer', name='Existing Actor', asset_id=1, role='performer', source='user:manual')
        self.save(purpose='category', name='', assignments={'performers': ['Added Actor']})
        with self.contract.read_connection() as connection:
            names = {row[0] for row in connection.execute("SELECT e.canonical_name FROM entity e JOIN asset_entity ae ON ae.entity_id=e.id WHERE ae.asset_id=1")}
            self.assertEqual(names, {'Existing Actor', 'Added Actor'})

    def test_background_metadata_applies_large_frozen_selection_in_bounded_groups(self):
        with self.contract.write_transaction() as connection:
            connection.executemany("INSERT INTO asset(location,path,name,medium) VALUES('local',?,?,'video')",
                [(f'R:\\Media\\精选\\作者甲\\{i}.mp4', f'{i}.mp4') for i in range(250)])
        ids = web_folders.q_folder_selection(self.contract, {'folder': self.key()})['ids']
        state = web_metadata_jobs.w_metadata_job(self.contract, {'kind': 'batch', 'payload': {
            'ids': ids, 'operation': 'actor', 'name': 'Jane Doe'}})
        result = self.edit_result(state)
        self.assertEqual(result['job_id'], state['job_id'])
        self.assertEqual((result['status'], result['checked'], result['total']), ('complete', 252, 252))
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id WHERE e.canonical_name='Jane Doe'").fetchone()[0], 252)
        state = web_metadata_jobs.w_metadata_job(self.contract, {'kind': 'batch', 'payload': {
            'ids': ids, 'operation': 'studio', 'name': 'Folder Studio'}})
        self.assertEqual(self.edit_result(state)['status'], 'complete')
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM asset WHERE studio='Folder Studio'").fetchone()[0], 252)

    def test_edits_wait_in_submission_order_and_continue_after_failure(self):
        entered, release = threading.Event(), threading.Event()
        applied = []
        def work(contract, payload):
            applied.append((payload['name'], tuple(payload['ids'])))
            if payload['name'] == 'First':
                entered.set()
                release.wait(10)
                raise ValueError('test edit failure')
            return {'ok': True}
        with patch('peach.web_batch.w_batch', side_effect=work):
            body = {'kind': 'batch', 'payload': {'ids': [1], 'operation': 'actor', 'name': 'First'}}
            first = web_metadata_jobs.w_metadata_job(self.contract, body)
            try:
                self.assertTrue(entered.wait(5))
                body['payload']['name'] = 'Second'
                body['payload']['ids'] = [2]
                second = web_metadata_jobs.w_metadata_job(self.contract, body)
                body['payload']['name'] = 'Third'
                body['payload']['ids'] = [3]
                third = web_metadata_jobs.w_metadata_job(self.contract, body)
                body['payload']['name'] = 'Changed after submission'
                body['payload']['ids'][0] = 4
                self.assertEqual((second['status'], second['queue_position']), ('queued', 1))
                self.assertEqual((third['status'], third['queue_position']), ('queued', 2))
                self.assertEqual(applied, [('First', (1,))])
            finally:
                release.set()
                result = self.edit_result(first)
                second_result = self.edit_result(second) if 'second' in locals() else None
                third_result = self.edit_result(third) if 'third' in locals() else None
        self.assertEqual(result['status'], 'failed')
        self.assertIn('test edit failure', result['error'])
        self.assertEqual(second_result['status'], 'complete')
        self.assertEqual(third_result['status'], 'complete')
        self.assertEqual(applied, [('First', (1,)), ('Second', (2,)), ('Third', (3,))])
        self.assertEqual(len({first['job_id'], second['job_id'], third['job_id']}), 3)
        self.assertEqual(len(web_metadata_jobs.q_metadata_job(self.contract, {})['jobs']), 3)

    def test_failed_batch_retains_actual_completed_count(self):
        with patch('peach.web_batch.w_batch', side_effect=[{'ok': True}, ValueError('second batch failed')]) as apply:
            state = web_metadata_jobs.w_metadata_job(self.contract, {'kind': 'batch', 'payload': {
                'ids': list(range(1, 253)), 'operation': 'actor', 'name': 'Jane Doe'}})
            result = self.edit_result(state)
        self.assertEqual((result['status'], result['checked'], result['total']), ('failed', 200, 252))
        self.assertEqual([len(call.args[1]['ids']) for call in apply.call_args_list], [200, 52])

    def test_preview_is_read_only_and_save_projects_with_own_source(self):
        preview = web_folders.w_folder_preview(self.contract, self.rule())
        self.assertEqual((preview['total'], preview['applicable']), (2, 2))
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM asset_entity').fetchone()[0], 0)
        self.assertEqual(self.save()['applied'], 2)
        with self.contract.read_connection() as connection:
            values = connection.execute('SELECT id,creator,field_owners FROM asset ORDER BY id').fetchall()
            self.assertEqual([row['creator'] for row in values], ['作者甲', '作者甲', None, None])
            self.assertEqual(json.loads(values[0]['field_owners'])['creator'], 'user:directory-' + self.key())

    def test_changed_contents_reject_frozen_preview(self):
        body = self.rule()
        preview = web_folders.w_folder_preview(self.contract, body)
        with self.contract.write_transaction() as connection:
            write_owned_fields(connection, [1], {'creator': '其他人'}, 'user:manual')
        with self.assertRaisesRegex(ValueError, '重新预览'):
            web_folders.w_folder_rule(self.contract, {**body, 'action': 'save', 'expected_revision': 0,
                                                     'plan_version': preview['plan_version']})

    def test_conflicts_keep_manual_and_external_relations(self):
        with self.contract.write_transaction() as connection:
            write_owned_fields(connection, [1], {'creator': '其他人'}, 'user:manual')
            upsert_asset_entity(connection, kind='creator', name='其他人', asset_id=1, role='creator', source='user:manual')
        result = self.save()
        self.assertEqual((result['applied'], result['conflicts']), (1, 1))
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute('SELECT creator FROM asset WHERE id=1').fetchone()[0], '其他人')

    def test_remove_rule_only_withdraws_its_source_and_preserves_later_manual_edit(self):
        self.save()
        with self.contract.write_transaction() as connection:
            write_owned_fields(connection, [1], {'creator': '手动归属'}, 'user:manual')
        web_folders.w_folder_rule(self.contract, {'folder': self.key(), 'action': 'remove', 'expected_revision': 1})
        with self.contract.read_connection() as connection:
            self.assertEqual([row[0] for row in connection.execute('SELECT creator FROM asset WHERE id IN (1,2) ORDER BY id')], ['手动归属', None])
            self.assertEqual(connection.execute('SELECT count(*) FROM asset_entity').fetchone()[0], 0)

    def test_new_files_follow_enabled_rule_and_child_category_stops_inheritance(self):
        self.save(future=True)
        child = self.key('R:\\Media\\精选\\作者甲\\视频')
        self.save(folder=child, purpose='category', name='', future=False)
        with self.contract.write_transaction() as connection:
            for suffix in ('new.mp4', '视频\\new.mp4'):
                connection.execute("INSERT INTO asset(location,path,name,medium) VALUES('local',?,'new.mp4','video')",
                                   ('R:\\Media\\精选\\作者甲\\' + suffix,))
            self.assertEqual(folder_rules.apply_new(connection, [5, 6]), 1)
            self.assertEqual([row[0] for row in connection.execute('SELECT creator FROM asset WHERE id IN (5,6) ORDER BY id')], ['作者甲', None])

    def test_subfolder_actor_rule_persists_inherits_and_withdraws_its_cast(self):
        with self.contract.write_transaction() as connection:
            upsert_asset_entity(connection, kind='performer', name='手动演员', asset_id=2,
                                role='performer', source='user:manual')
        self.save(purpose='category', name='', actors_from_subfolders=True, future=True)
        saved = self.read(folder=self.key())['rule']
        self.assertTrue(saved['actors_from_subfolders'])
        self.assertTrue(saved['future'])
        with self.contract.write_transaction() as connection:
            def cast(asset_id):
                return [row[0] for row in connection.execute(
                    "SELECT e.canonical_name FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id "
                    "WHERE ae.asset_id=? AND e.kind='performer' ORDER BY e.canonical_name", (asset_id,))]
            self.assertEqual(cast(1), [])
            self.assertEqual(set(cast(2)), {'手动演员', '视频'})
            new_id = connection.execute(
                "INSERT INTO asset(location,path,name,medium) VALUES('local',?,'new.mp4','video')",
                ('R:\\Media\\精选\\作者甲\\Alex\\new.mp4',)).lastrowid
            self.assertEqual(folder_rules.apply_new(connection, [new_id]), 1)
            self.assertEqual(cast(new_id), ['Alex'])
            self.assertEqual(folder_rules.apply_new(connection, [new_id]), 0)
        web_folders.w_folder_rule(self.contract, {
            'folder': self.key(), 'action': 'remove', 'expected_revision': self.read()['rules_revision']})
        with self.contract.read_connection() as connection:
            self.assertEqual([tuple(row) for row in connection.execute(
                "SELECT ae.asset_id,e.canonical_name FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id "
                "WHERE e.kind='performer' ORDER BY ae.asset_id")], [(2, '手动演员')])

    def test_withdrawal_restores_an_empty_automatic_field_owner(self):
        with self.contract.write_transaction() as connection:
            write_owned_fields(connection, [1], {'creator': ''}, 'auto:seed')
        self.save()
        web_folders.w_folder_rule(self.contract, {'folder': self.key(), 'action': 'remove', 'expected_revision': 1})
        with self.contract.read_connection() as connection:
            row = connection.execute('SELECT creator,field_owners FROM asset WHERE id=1').fetchone()
            self.assertEqual(row['creator'], '')
            self.assertEqual(json.loads(row['field_owners'])['creator'], 'auto:seed')

    def test_rule_revision_rejects_concurrent_form_and_edit_replaces_own_projection(self):
        self.save()
        self.assertEqual(self.save(name='作者乙')['applied'], 2)
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute('SELECT creator FROM asset WHERE id=1').fetchone()[0], '作者乙')
        with self.assertRaisesRegex(ValueError, '规则已变化'):
            web_folders.w_folder_rule(self.contract, {'folder': self.key(), 'action': 'remove', 'expected_revision': 0})

    def test_narrowing_rule_previews_withdrawal_and_binds_omitted_descendants(self):
        self.save()
        body = self.rule(recursive=False)
        preview = web_folders.w_folder_preview(self.contract, body)
        self.assertEqual((preview['total'], preview['withdrawn']), (1, 2))
        with self.contract.write_transaction() as connection:
            write_owned_fields(connection, [2], {'creator': '逐件确认'}, 'user:manual')
        with self.assertRaisesRegex(ValueError, '重新预览'):
            web_folders.w_folder_rule(self.contract, {**body, 'action': 'save', 'expected_revision': 1,
                                                     'plan_version': preview['plan_version']})
        self.save(recursive=False)
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute('SELECT creator FROM asset WHERE id=2').fetchone()[0], '逐件确认')

    def test_performer_and_seller_use_existing_entity_contracts(self):
        self.save(purpose='performer', name='演示人物')
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM asset_tag WHERE tag='演员:演示人物'").fetchone()[0], 2)
        self.save(purpose='seller', name='演示卖家')
        with self.contract.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM entity_classification WHERE value='seller' AND status='approved'").fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM asset_tag').fetchone()[0], 0)

    def test_unknown_and_removed_directories_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '目录不存在'):
            self.read(folder='missing')
        with self.contract.write_transaction() as connection:
            connection.execute("UPDATE asset SET disposal='trash' WHERE id IN (1,2)")
        with self.assertRaisesRegex(ValueError, '目录不存在'):
            self.read(folder=self.key())

    def test_scan_inherits_only_explicitly_enabled_directory_rule(self):
        self.save(future=True)
        media = self.root / 'media'
        target = media / '精选' / '作者甲' / 'scan.mp4'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'synthetic media')
        result = scan.scan_location(self.path, 'local', 'R:\\Media',
                                    declared_roots={'local': ('R:\\Media',)}, mounts={'local': (media,)},
                                    windows=False, report=lambda _message: None)
        self.assertEqual(len(result.new_ids), 1)
        with self.contract.read_connection() as connection:
            value = connection.execute('SELECT creator FROM asset WHERE id=?', (result.new_ids[0],)).fetchone()[0]
        self.assertEqual(value, '作者甲')

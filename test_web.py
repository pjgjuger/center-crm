import copy
import unittest
from unittest.mock import patch

from service import can_access, reports_for_card, sync_surveys
from storage import Store, ConflictError


class Snapshot:
    def __init__(self, ref):
        self.id = ref.id
        self.value = copy.deepcopy(ref.db.data.get(ref.path))
        self.exists = self.value is not None

    def to_dict(self):
        return copy.deepcopy(self.value)


class Ref:
    def __init__(self, db, path):
        self.db, self.path, self.id = db, path, path.split('/')[-1]

    def document(self, ident):
        return Ref(self.db, self.path + '/' + ident)

    collection = document

    def get(self, transaction=None):
        if transaction and transaction.writing:
            raise AssertionError('Firestore transactions must read before writing')
        return Snapshot(self)

    def stream(self):
        prefix = self.path + '/'
        return [Snapshot(Ref(self.db, key)) for key in self.db.data
                if key.startswith(prefix) and '/' not in key[len(prefix):]]


class Tx:
    def __init__(self, db):
        self.db, self.writing = db, False

    def set(self, ref, value):
        self.writing = True
        self.db.data[ref.path] = copy.deepcopy(value)

    def create(self, ref, value):
        assert ref.path not in self.db.data
        self.set(ref, value)

    def delete(self, ref):
        self.writing = True
        self.db.data.pop(ref.path, None)

    def commit(self):
        pass


class DB:
    def __init__(self):
        self.data = {}

    def transaction(self):
        return Tx(self)

    batch = transaction


def fake_store(db=None):
    store = Store.__new__(Store)
    store.client = db or DB()
    store.root = Ref(store.client, 'owners/test')
    for name in ('cards', 'surveys', 'identities'):
        setattr(store, name, store.root.collection(name))
    return store


class DurableWorkflow(unittest.TestCase):
    def setUp(self):
        self.decorator = patch('storage.firestore.transactional', lambda f: f)
        self.decorator.start()
        self.addCleanup(self.decorator.stop)
        self.store = fake_store()
        self.fm = {'상호': '테스트 매장', '지역': '서울', '연락처': '010-1234-5678', '이메일주소': 'test@example.com'}

    def test_verified_owner_only(self):
        self.assertTrue(can_access({'email_verified': True, 'email': 'OWNER@example.com'}, 'owner@example.com'))
        for value in ({}, {'email_verified': 'true', 'email': 'owner@example.com'},
                      {'email_verified': True, 'email': 'stranger@example.com'}):
            self.assertFalse(can_access(value, 'owner@example.com'))

    def test_login_runtime_dependencies(self):
        from authlib.integrations.starlette_client import OAuth
        self.assertIsNotNone(OAuth())

    def test_restart_dedup_delete_restore(self):
        record = (2, self.fm, 'response1')
        self.assertEqual(sync_surveys(self.store, [record])['added'], 1)
        restarted = fake_store(self.store.client)
        self.assertEqual(sync_surveys(restarted, [record])['added'], 0)
        card = restarted.list_cards()[0]
        restarted.update(card['id'], 1, deleted=True)
        self.assertEqual(sync_surveys(restarted, [record])['added'], 0)
        self.assertEqual(restarted.list_cards(), [])
        self.assertEqual(len(restarted.list_cards(deleted=True)), 1)
        restarted.update(card['id'], 2, deleted=False)
        self.assertEqual(len(restarted.list_cards()), 1)

    def test_conflicting_mobile_edit_rejected(self):
        ident, _ = self.store.create(self.fm, 'original')
        phone = fake_store(self.store.client)
        self.store.update(ident, 1, body='PC edit')
        with self.assertRaises(ConflictError):
            phone.update(ident, 1, body='stale phone edit')
        self.assertEqual(phone.get(ident)['body'], 'PC edit')

    def test_changed_identity_and_duplicate_link(self):
        ident, _ = self.store.create(self.fm)
        changed = {**self.fm, '상호': '바뀐 매장'}
        self.store.update(ident, 1, fm=changed)
        linked, created = self.store.create(changed, source_id='second-response')
        self.assertEqual(linked, ident)
        self.assertFalse(created)

    def test_assets_round_trip(self):
        raw = ('상담 보고서\n' * 100).encode()
        ident = self.store.put_asset('report.md', raw, 'text/markdown')
        self.assertEqual(fake_store(self.store.client).get_asset(ident)[1], raw)

    def test_report_resolution_current_and_legacy(self):
        card = {'fm': {'최근보고서ID': 'new'}, 'body': '## SEO 보고서\n보고서: 예전_SEO.md\n[[보고서/더예전.md]]'}
        assets = [{'id': 'old', 'name': '보고서/예전_SEO.md'},
                  {'id': 'new', 'name': '최신.md'}, {'id': 'older', 'name': '더예전.md'},
                  {'id': 'other', 'name': '다른고객.md'}]
        found = reports_for_card(card, assets)
        self.assertEqual(found[0]['id'], 'new')
        self.assertEqual({x['id'] for x in found}, {'new', 'old', 'older'})

    def test_migration_preserves_live_and_trashed_versions(self):
        self.store.create(self.fm, 'deleted history', legacy_id='old', source_id='one', deleted=True)
        self.store.create(self.fm, 'active history', legacy_id='current', source_id='one')
        self.assertEqual(self.store.get('old')['body'], 'deleted history')
        self.assertEqual(self.store.get('current')['body'], 'active history')
        self.assertEqual(self.store.survey_state()['one']['card_id'], 'current')

    def test_unauthenticated_app_stops_before_database(self):
        from streamlit.testing.v1 import AppTest
        with patch('storage.Store') as constructor:
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            constructor.assert_not_called()
            self.assertTrue(app.info)


if __name__ == '__main__':
    unittest.main()

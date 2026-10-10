import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from cpc_integration import Integration, handle, problem_key


class CpcTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.patch=patch.multiple(app,DATA_DIR=root,DB_PATH=root/'db.sqlite',CACHE_DIR=root/'cache',HTTP_CACHE_DIR=root/'cache/http')
        self.patch.start();app.init_db();self.service=Integration(app)

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_platform_aliases_match_existing_catalog(self):
        for platform,value in [('codeforces','105657A'),('vjudge','Gym-105657A'),('luogu','CF105657A')]:
            self.assertEqual(problem_key(platform,value),'codeforces:105657A')
        self.assertEqual(self.service.aliases['qoj:9726'],self.service.aliases['codeforces:105657A'])

    def test_read_token_rotation_and_unknown_owner(self):
        first=self.service.issue_token('1')['token']
        second=self.service.issue_token('1')['token']
        self.assertIsNone(self.service.token_owner(first))
        self.assertEqual(self.service.token_owner(second),'1')
        self.assertIsNone(self.service.token_owner('invalid'))

    def test_cross_origin_write_does_not_issue_token(self):
        class Handler:
            path='/api/cpc/token'
            headers={'Origin':'https://evil.example','Host':'wall.example'}
            def send_error_json(self,status,message):self.status=status
        handler=Handler()
        with patch.object(app,'get_current_principal',return_value={'type':'user','id':'1'}):
            handle(handler,self.service,post=True)
        self.assertEqual(handler.status,403)
        with self.service.db() as db:self.assertEqual(db.execute('select count(*) from cpc_read_tokens').fetchone()[0],0)

    def test_unknown_scoreboard_problem_is_atomic(self):
        body={'confirmed':True,'contest_id':'icpc-2024-杭州','accepted':['A','INVALID'],
              'source_url':'https://example.com/final','source_row':'1'}
        with self.assertRaises(ValueError):self.service.import_onsite(body)
        with self.service.db() as db:self.assertEqual(db.execute('select count(*) from cpc_onsite').fetchone()[0],0)

    def test_catalog_mapping_overrides_replay_link_with_a_missing_gym_letter(self):
        cid='ccpc-2020-秦皇岛'
        participation={'id':'historical','team':'原队伍','date':'2020-10-18'}
        body={'contest_id':cid,'problem_labels':list('ABCDEFGHIJKL'),'accepted':['A','C'],
              'reference_urls':['https://codeforces.com/gym/102769'],
              'participation_id':participation['id'],'team':participation['team'],
              'contest_date':participation['date'],'source_url':'https://rl.algoux.cn/ranklist/ccpc2020qinhuangdao'}
        with patch.object(self.service,'remote',return_value=({'roster':{'participations':[participation]}},0)):
            key=self.service.import_auto_onsite(body)
        with self.service.db() as db:
            saved=json.loads(db.execute('select body from cpc_onsite where id=?',(key,)).fetchone()[0])
        self.assertEqual(saved['accepted'],[cid+':A',cid+':C'])
        self.assertEqual(saved['problem_aliases'][cid+':A'],'codeforces:102769A')
        self.assertNotIn(cid+':C',saved['problem_aliases'])

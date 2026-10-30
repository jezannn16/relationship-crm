import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app import connect
from telegram_bot import handle_update
from telegram_runtime import process_update
from telegram_api import TelegramAPI,TelegramDeliveryUncertain

class FakeAPI:
 def __init__(self):self.sent=[]
 def send_message(self,chat,text):self.sent.append((str(chat),text))

def update(uid,chat,text,kind='private'):
 return {'update_id':uid,'message':{'from':{'id':chat},'chat':{'id':chat,'type':kind},'text':text}}

class CRMTelegramTests(unittest.TestCase):
 def test_live_token_probe_calls_only_get_me(self):
  calls=[]
  api=TelegramAPI('123:secret',request_fn=lambda method,params,timeout:(calls.append((method,params)) or {'ok':True,'result':{'id':123,'username':'test_bot'}}))
  self.assertEqual(api.get_me()['username'],'test_bot')
  self.assertEqual(calls,[('getMe',{})])
 def test_send_network_timeout_is_classified_uncertain(self):
  from unittest.mock import patch
  api=TelegramAPI('123:synthetic')
  with patch('telegram_api.urlopen',side_effect=TimeoutError()):
   with self.assertRaises(TelegramDeliveryUncertain):api.send_message('101','synthetic response')
  api=TelegramAPI('123:synthetic',request_fn=lambda *args:{'ok':False,'error_code':500})
  with self.assertRaises(TelegramDeliveryUncertain):api.send_message('101','synthetic response')

 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'crm.sqlite');self.api=FakeAPI()
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_allowlist_private_capture_confirmation_and_scoping(self):
  with patch.dict(os.environ,{'CRM_ALLOWED_USER_IDS':'101','CRM_TIMEZONE':'Europe/Moscow'}):
   out=handle_update(update(1,999,'/contacts'),self.db);self.assertIn('not enabled',out[0][1])
   out=handle_update(update(2,101,'/capture Met with Alice from ExampleCo, discussed quarterly plan, follow-up Friday'),self.db)
   self.assertIn('Please confirm',out[0][1]);self.assertEqual(self.db.execute('select count(*) from contacts').fetchone()[0],0)
   self.db.commit()
   process_update(self.db,self.api,handle_update,update(3,101,'/confirm'))
   self.assertEqual(self.db.execute('select count(*) from contacts where user_id="101"').fetchone()[0],1)
   self.assertEqual(self.db.execute('select count(*) from interactions where user_id="101"').fetchone()[0],1)
   self.assertEqual(self.db.execute('select count(*) from followups where user_id="101"').fetchone()[0],1)
   self.assertEqual(handle_update(update(4,101,'/contacts','group'),self.db),[])
 def test_update_idempotency_and_outbox(self):
  with patch.dict(os.environ,{'CRM_ALLOWED_USER_IDS':'101'}):
   u=update(10,101,'/add Alice | alice@example.test | Acme')
   self.assertTrue(process_update(self.db,self.api,handle_update,u));self.assertFalse(process_update(self.db,self.api,handle_update,u))
   self.assertEqual(self.db.execute('select count(*) from contacts').fetchone()[0],1);self.assertEqual(len(self.api.sent),1)
 def test_outbox_claim_lost_to_another_worker_does_not_send_twice(self):
  from telegram_runtime import flush_outbox
  self.db.execute("INSERT INTO telegram_outbox(update_id,sequence,chat_id,text,created_at,status) VALUES(?,?,?,?,?,'queued')",(90,0,'101','synthetic response','now'));self.db.commit()
  class RacingDB:
   raced=False
   def commit(inner):self.db.commit()
   def execute(inner,sql,args=()):
    result=self.db.execute(sql,args)
    if sql.startswith('SELECT * FROM telegram_outbox') and not inner.raced:
     inner.raced=True;self.db.execute("UPDATE telegram_outbox SET status='sent' WHERE update_id=90");self.db.commit()
    return result
  flush_outbox(RacingDB(),self.api)
  self.assertEqual(self.api.sent,[])
 def test_schema_migrations_are_recorded(self):
  versions=[r[0] for r in self.db.execute('select version from schema_migrations order by version')]
  self.assertEqual(versions,[1,2,3,4]);self.assertIsNotNone(self.db.execute('select 1 from sqlite_master where name="contact_projects"').fetchone())
  self.assertIsNotNone(self.db.execute('select 1 from sqlite_master where name="briefing_settings"').fetchone())
 def test_briefing_includes_due_and_stale_contacts_scoped_to_user(self):
  with patch.dict(os.environ,{'CRM_ALLOWED_USER_IDS':'101','CRM_TIMEZONE':'Europe/Moscow'}):
   self.db.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('101','Synthetic stale','2000-01-01T00:00:00+00:00'))
   self.db.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('202','Other user','2000-01-01T00:00:00+00:00'))
   result=handle_update(update(20,101,'/briefing 30'),self.db)[0][1]
   self.assertIn('Synthetic stale',result);self.assertNotIn('Other user',result);self.assertIn('Follow-ups due or overdue',result)
if __name__=='__main__':unittest.main()

import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app import connect
from telegram_bot import handle_update
from telegram_runtime import process_update

class FakeAPI:
 def __init__(self):self.sent=[]
 def send_message(self,chat,text):self.sent.append((str(chat),text))

def update(uid,chat,text,kind='private'):
 return {'update_id':uid,'message':{'from':{'id':chat},'chat':{'id':chat,'type':kind},'text':text}}

class CRMTelegramTests(unittest.TestCase):
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
 def test_schema_migrations_are_recorded(self):
  versions=[r[0] for r in self.db.execute('select version from schema_migrations order by version')]
  self.assertEqual(versions,[1,2,3]);self.assertIsNotNone(self.db.execute('select 1 from sqlite_master where name="contact_projects"').fetchone())
if __name__=='__main__':unittest.main()

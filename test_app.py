import tempfile,unittest,csv,subprocess,sys
from pathlib import Path
import app
class CRMTests(unittest.TestCase):
 def test_edit_contact_and_delete_interaction_and_followup_are_owner_scoped(self):
  with tempfile.TemporaryDirectory() as td:
   db_path=Path(td)/'crm.db';d=app.connect(db_path)
   c=d.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('alice','Synthetic contact','now')).lastrowid
   interaction=d.execute('INSERT INTO interactions(user_id,contact_id,note,occurred_at) VALUES(?,?,?,?)',('alice',c,'Synthetic meeting','2026-01-01')).lastrowid
   followup=d.execute('INSERT INTO followups(user_id,contact_id,note,due_date) VALUES(?,?,?,?)',('alice',c,'Synthetic follow-up','2026-02-01')).lastrowid;d.commit();d.close()
   def cli(user,*args):return subprocess.run([sys.executable,'app.py','--db',str(db_path),'--user',user,*args],capture_output=True,text=True)
   edited=cli('alice','edit',str(c),'--name','Updated contact','--email','updated@example.test','--notes','Updated synthetic note')
   self.assertEqual(edited.returncode,0,edited.stderr)
   forbidden=cli('bob','edit',str(c),'--name','Leaked')
   self.assertNotEqual(forbidden.returncode,0)
   self.assertNotEqual(cli('bob','delete-interaction',str(interaction),'--confirm').returncode,0)
   self.assertEqual(cli('alice','delete-interaction',str(interaction),'--confirm').returncode,0)
   self.assertEqual(cli('alice','delete-followup',str(followup),'--confirm').returncode,0)
   check=app.connect(db_path)
   self.assertEqual(tuple(check.execute('SELECT name,email,notes FROM contacts WHERE id=?',(c,)).fetchone()),('Updated contact','updated@example.test','Updated synthetic note'))
   self.assertEqual(check.execute('SELECT COUNT(*) FROM interactions').fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM followups').fetchone()[0],0)
   check.close()
 def test_owner_scope_and_confirmed_merge(self):
  with tempfile.TemporaryDirectory() as td:
   d=app.connect(Path(td)/'crm.db');a=d.execute('insert into contacts(user_id,name,created_at) values(?,?,?)',('u1','Anna','now')).lastrowid;b=d.execute('insert into contacts(user_id,name,created_at) values(?,?,?)',('u1','Anna','now')).lastrowid
   app.owned(d,'u1',a)
   with self.assertRaises(ValueError):app.owned(d,'u2',a)
   d.execute('insert into interactions(user_id,contact_id,note,occurred_at) values(?,?,?,?)',('u1',b,'Met','2026-01-01'));d.execute('update interactions set contact_id=? where contact_id=? and user_id=?',(a,b,'u1'));d.execute('delete from contacts where id=? and user_id=?',(b,'u1'))
   self.assertEqual(d.execute('select contact_id from interactions').fetchone()[0],a);d.close()
 def test_followup_date_validation(self):
  from datetime import datetime
  with self.assertRaises(ValueError):datetime.strptime('tomorrow','%Y-%m-%d')
 def test_cli_csv_export_includes_related_records(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'crm.db';out=Path(td)/'contacts.csv';conn=app.connect(db)
   cid=conn.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('demo','Synthetic','now')).lastrowid
   conn.execute('INSERT INTO interactions(user_id,contact_id,note,occurred_at) VALUES(?,?,?,?)',('demo',cid,'Met','now'))
   conn.execute('INSERT INTO followups(user_id,contact_id,note,due_date) VALUES(?,?,?,?)',('demo',cid,'Call','2026-11-01'));conn.commit();conn.close()
   result=subprocess.run([sys.executable,'app.py','--db',str(db),'--user','demo','export',str(out)],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   with out.open(encoding='utf-8',newline='') as file:row=next(csv.DictReader(file))
   self.assertIn('Met',row['interactions_json']);self.assertIn('Call',row['followups_json'])
 def test_delete_user_data_requires_confirmation_and_removes_organization(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'crm.db';conn=app.connect(db)
   conn.execute('INSERT INTO organizations(user_id,name) VALUES(?,?)',('demo','Synthetic org'));conn.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('demo','Synthetic','now'));conn.commit();conn.close()
   conn=app.connect(db);conn.execute('INSERT INTO notification_log(user_id,notification_key,sent_at) VALUES(?,?,?)',('demo','briefing:2026-01-01','now'));conn.execute("INSERT INTO telegram_outbox(update_id,sequence,chat_id,text,created_at) VALUES(1,0,'demo','Synthetic private output','now')");conn.commit();conn.close()
   denied=subprocess.run([sys.executable,'app.py','--db',str(db),'--user','demo','delete-user-data'],capture_output=True,text=True)
   self.assertNotEqual(denied.returncode,0)
   done=subprocess.run([sys.executable,'app.py','--db',str(db),'--user','demo','delete-user-data','--confirm'],capture_output=True,text=True)
   self.assertEqual(done.returncode,0,done.stderr);check=app.connect(db)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM organizations WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM contacts WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM notification_log WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM telegram_outbox WHERE chat_id=?',('demo',)).fetchone()[0],0);check.close()
if __name__=='__main__':unittest.main()

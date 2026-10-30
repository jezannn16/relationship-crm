import tempfile,unittest,csv,subprocess,sys,sqlite3,json
from pathlib import Path
import app
import migrations
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
 def test_tag_assign_remove_and_listing_are_owner_scoped(self):
  with tempfile.TemporaryDirectory() as td:
   db_path=Path(td)/'crm.db';d=app.connect(db_path)
   contact=d.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('alice','Synthetic tagged contact','now')).lastrowid;d.commit();d.close()
   def cli(user,*args):return subprocess.run([sys.executable,'app.py','--db',str(db_path),'--user',user,*args],capture_output=True,text=True)
   self.assertEqual(cli('alice','tag',str(contact),'priority').returncode,0)
   self.assertIn('priority',cli('alice','tags').stdout)
   self.assertNotIn('priority',cli('bob','tags').stdout)
   self.assertNotEqual(cli('bob','untag',str(contact),'priority').returncode,0)
   self.assertEqual(cli('alice','untag',str(contact),'priority').returncode,0)
   self.assertNotIn('priority',cli('alice','tags').stdout)
 def test_upgrade_from_v3_adds_scheduler_and_outbox_columns(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'old.sqlite3';old=sqlite3.connect(path)
   old.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)')
   for version,migration in enumerate((migrations._v1,migrations._v2,migrations._v3),1):
    migration(old);old.execute('INSERT INTO schema_migrations VALUES(?,?)',(version,'synthetic'))
   old.commit();old.close();upgraded=app.connect(path)
   cols={r['name'] for r in upgraded.execute('PRAGMA table_info(telegram_outbox)')}
   self.assertTrue({'attempt_count','dedupe_key','notification_key'}<=cols)
   self.assertEqual(upgraded.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],4)
   upgraded.close()
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
 def test_json_export_preserves_owner_catalog_and_contact_links_without_cross_user_data(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'crm.db';out=Path(td)/'owner.json';conn=app.connect(db)
   cid=conn.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('alice','Synthetic Alice','now')).lastrowid
   other=conn.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('bob','Synthetic Bob','now')).lastrowid
   tag=conn.execute('INSERT INTO tags(user_id,name) VALUES(?,?)',('alice','priority')).lastrowid
   conn.execute('INSERT INTO tags(user_id,name) VALUES(?,?)',('bob','private-tag'))
   project=conn.execute('INSERT INTO projects(user_id,name,description) VALUES(?,?,?)',('alice','Synthetic project','Project notes')).lastrowid
   conn.execute('INSERT INTO projects(user_id,name) VALUES(?,?)',('bob','Other project'))
   conn.execute('INSERT INTO contact_tags(contact_id,tag_id) VALUES(?,?)',(cid,tag))
   conn.execute('INSERT INTO contact_projects(contact_id,project_id) VALUES(?,?)',(cid,project))
   conn.execute('INSERT INTO organizations(user_id,name,notes) VALUES(?,?,?)',('alice','Synthetic org','Organization notes'))
   conn.execute('INSERT INTO organizations(user_id,name) VALUES(?,?)',('bob','Other org'));conn.commit();conn.close()
   result=subprocess.run([sys.executable,'app.py','--db',str(db),'--user','alice','export',str(out),'--format','json'],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr);bundle=json.loads(out.read_text(encoding='utf-8'))
   self.assertEqual([r['name'] for r in bundle['contacts']],['Synthetic Alice'])
   self.assertEqual(bundle['contacts'][0]['tags'],['priority']);self.assertEqual(bundle['contacts'][0]['projects'],['Synthetic project'])
   self.assertEqual(bundle['tags'],[{'name':'priority'}]);self.assertEqual(bundle['projects'],[{'name':'Synthetic project','description':'Project notes'}])
   self.assertEqual(bundle['organizations'],[{'name':'Synthetic org','notes':'Organization notes'}])
   self.assertNotIn(str(other),out.read_text(encoding='utf-8'))
 def test_delete_user_data_requires_confirmation_and_removes_organization(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'crm.db';conn=app.connect(db)
   conn.execute('INSERT INTO organizations(user_id,name) VALUES(?,?)',('demo','Synthetic org'));conn.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',('demo','Synthetic','now'));conn.commit();conn.close()
   conn=app.connect(db);conn.execute('INSERT INTO notification_log(user_id,notification_key,sent_at) VALUES(?,?,?)',('demo','briefing:2026-01-01','now'));conn.execute("INSERT INTO telegram_outbox(update_id,sequence,chat_id,text,created_at) VALUES(1,0,'demo','Synthetic private output','now')");conn.execute("INSERT INTO briefing_settings(user_id,timezone) VALUES('demo','Europe/Moscow')");conn.commit();conn.close()
   denied=subprocess.run([sys.executable,'app.py','--db',str(db),'--user','demo','delete-user-data'],capture_output=True,text=True)
   self.assertNotEqual(denied.returncode,0)
   done=subprocess.run([sys.executable,'app.py','--db',str(db),'--user','demo','delete-user-data','--confirm'],capture_output=True,text=True)
   self.assertEqual(done.returncode,0,done.stderr);check=app.connect(db)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM organizations WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM contacts WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM notification_log WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM briefing_settings WHERE user_id=?',('demo',)).fetchone()[0],0)
   self.assertEqual(check.execute('SELECT COUNT(*) FROM telegram_outbox WHERE chat_id=?',('demo',)).fetchone()[0],0);check.close()
if __name__=='__main__':unittest.main()

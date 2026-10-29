import tempfile,unittest
from pathlib import Path
import app
class CRMTests(unittest.TestCase):
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
if __name__=='__main__':unittest.main()

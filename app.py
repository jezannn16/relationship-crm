"""Single-user-local CRM with explicit owner scoping and auditable destructive actions."""
from __future__ import annotations
import argparse,csv,json,os,sqlite3
from migrations import connect as connect_db
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
DB=Path(__file__).with_name('crm.sqlite3')
MAX_DELIVERY_ATTEMPTS=3
def connect(path=DB):
 return connect_db(path)

def audit(d,u,event,eid=None): d.execute('INSERT INTO audit(user_id,event,entity_id,created_at) VALUES(?,?,?,?)',(u,event,eid,datetime.now(timezone.utc).isoformat()))
def owned(d,u,cid):
 r=d.execute('SELECT * FROM contacts WHERE id=? AND user_id=?',(cid,u)).fetchone()
 if r is None: raise ValueError('Contact not found for this user')
 return r
def main():
 p=argparse.ArgumentParser(description='Local relationship CRM');p.add_argument('--db',type=Path,default=DB);p.add_argument('--user',required=True,help='Local owner key; all queries are scoped to it');s=p.add_subparsers(dest='cmd',required=True)
 q=s.add_parser('add');q.add_argument('name');q.add_argument('--email');q.add_argument('--org');q.add_argument('--notes',default='')
 q=s.add_parser('edit');q.add_argument('contact_id',type=int);q.add_argument('--name');q.add_argument('--email');q.add_argument('--org');q.add_argument('--notes')
 q=s.add_parser('search');q.add_argument('query',nargs='?',default='')
 q=s.add_parser('interaction');q.add_argument('contact_id',type=int);q.add_argument('note');q.add_argument('--at',default=datetime.now(timezone.utc).date().isoformat())
 q=s.add_parser('followup');q.add_argument('contact_id',type=int);q.add_argument('date');q.add_argument('note')
 q=s.add_parser('today');q.add_argument('--date',default=datetime.now(timezone.utc).date().isoformat())
 q=s.add_parser('history');q.add_argument('contact_id',type=int)
 q=s.add_parser('duplicates');q.add_argument('contact_id',type=int)
 q=s.add_parser('merge');q.add_argument('keep',type=int);q.add_argument('remove',type=int);q.add_argument('--confirm',action='store_true')
 q=s.add_parser('export');q.add_argument('file',type=Path);q.add_argument('--format',choices=['csv','markdown','json'],default='csv')
 q=s.add_parser('delete');q.add_argument('contact_id',type=int);q.add_argument('--confirm',action='store_true')
 q=s.add_parser('delete-interaction');q.add_argument('interaction_id',type=int);q.add_argument('--confirm',action='store_true')
 q=s.add_parser('delete-followup');q.add_argument('followup_id',type=int);q.add_argument('--confirm',action='store_true')
 q=s.add_parser('tag');q.add_argument('contact_id',type=int);q.add_argument('name')
 q=s.add_parser('untag');q.add_argument('contact_id',type=int);q.add_argument('name')
 q=s.add_parser('tags');q.add_argument('contact_id',type=int,nargs='?')
 q=s.add_parser('briefing-config');g=q.add_mutually_exclusive_group();g.add_argument('--enable',dest='enabled',action='store_true');g.add_argument('--disable',dest='enabled',action='store_false');q.set_defaults(enabled=None);q.add_argument('--timezone');q.add_argument('--quiet-start');q.add_argument('--quiet-end');q.add_argument('--stale-days',type=int)
 s.add_parser('dispatch-briefings',help='Queue enabled local-time briefings; does not send them')
 s.add_parser('delivery-status',help='List this owner’s persisted Telegram outbox status')
 q=s.add_parser('retry-delivery');q.add_argument('delivery_id',type=int);q.add_argument('--confirm',action='store_true')
 q=s.add_parser('delete-user-data');q.add_argument('--confirm',action='store_true')
 a=p.parse_args();d=connect(a.db);u=a.user
 try:
  if a.cmd=='add':
   name=a.name.strip()
   if not name: raise ValueError('Name is required')
   dup=d.execute('SELECT id FROM contacts WHERE user_id=? AND ((email IS NOT NULL AND lower(email)=lower(?)) OR (lower(name)=lower(?) AND lower(coalesce(organization,""))=lower(?)))',(u,a.email or '',name,a.org or '')).fetchall()
   cur=d.execute('INSERT INTO contacts(user_id,name,email,organization,notes,created_at) VALUES(?,?,?,?,?,?)',(u,name,a.email,a.org,a.notes,datetime.now(timezone.utc).isoformat()));audit(d,u,'contact.created',cur.lastrowid);d.commit();print(f'Created contact {cur.lastrowid}; possible duplicate IDs: '+', '.join(str(r['id']) for r in dup))
  elif a.cmd=='edit':
   current=owned(d,u,a.contact_id)
   changes={column:value for column,value in (('name',a.name),('email',a.email),('organization',a.org),('notes',a.notes)) if value is not None}
   if not changes:raise ValueError('Provide at least one field to edit')
   if 'name' in changes and not changes['name'].strip():raise ValueError('Name cannot be empty')
   changes={column:(value.strip() if value is not None else None) for column,value in changes.items()}
   d.execute('UPDATE contacts SET '+','.join(f'{column}=?' for column in changes)+' WHERE id=? AND user_id=?',(*changes.values(),a.contact_id,u));audit(d,u,'contact.updated',a.contact_id);d.commit();print(f'Updated contact {current["id"]}')
  elif a.cmd=='search':
   pat='%'+a.query+'%';rows=d.execute('SELECT c.*,max(i.occurred_at) last_contact FROM contacts c LEFT JOIN interactions i ON i.contact_id=c.id AND i.user_id=c.user_id WHERE c.user_id=? AND (c.name LIKE ? OR c.email LIKE ? OR c.organization LIKE ? OR c.notes LIKE ?) GROUP BY c.id ORDER BY c.name',(u,pat,pat,pat,pat)).fetchall();print('\n'.join(f"{r['id']} | {r['name']} | {r['organization'] or ''} | last={r['last_contact'] or 'never'}" for r in rows) or 'No contacts')
  elif a.cmd=='interaction':
   owned(d,u,a.contact_id);d.execute('INSERT INTO interactions(user_id,contact_id,note,occurred_at) VALUES(?,?,?,?)',(u,a.contact_id,a.note.strip(),a.at));audit(d,u,'interaction.created',a.contact_id);d.commit();print('Interaction saved')
  elif a.cmd=='followup':
   owned(d,u,a.contact_id);datetime.strptime(a.date,'%Y-%m-%d');d.execute('INSERT INTO followups(user_id,contact_id,note,due_date) VALUES(?,?,?,?)',(u,a.contact_id,a.note,a.date));audit(d,u,'followup.created',a.contact_id);d.commit();print('Follow-up saved')
  elif a.cmd=='today':
   rows=d.execute('SELECT f.id,c.name,f.note,f.due_date FROM followups f JOIN contacts c ON c.id=f.contact_id WHERE f.user_id=? AND c.user_id=? AND f.done=0 AND f.due_date<=? ORDER BY f.due_date',(u,u,a.date)).fetchall();print('\n'.join(f"{r['id']} {r['due_date']} {r['name']}: {r['note']}" for r in rows) or 'No follow-ups due')
  elif a.cmd=='history':
   owned(d,u,a.contact_id);rows=d.execute('SELECT occurred_at,note FROM interactions WHERE user_id=? AND contact_id=? ORDER BY occurred_at DESC',(u,a.contact_id)).fetchall();print('\n'.join(f"{r['occurred_at']}: {r['note']}" for r in rows) or 'No interactions')
  elif a.cmd=='duplicates':
   c=owned(d,u,a.contact_id);rows=d.execute('SELECT id,name,email,organization FROM contacts WHERE user_id=? AND id<>? AND (lower(name)=lower(?) OR (email IS NOT NULL AND lower(email)=lower(?)) OR (organization IS NOT NULL AND lower(organization)=lower(?)))',(u,c['id'],c['name'],c['email'] or '',c['organization'] or '')).fetchall();print('\n'.join(str(dict(x)) for x in rows) or 'No likely duplicates (name/email/organization exact match)')
  elif a.cmd=='merge':
   x=owned(d,u,a.keep);y=owned(d,u,a.remove)
   if a.keep==a.remove: raise ValueError('Choose two distinct contacts')
   if not a.confirm: raise ValueError('Review records, then repeat with --confirm')
   d.execute('UPDATE interactions SET contact_id=? WHERE contact_id=? AND user_id=?',(x['id'],y['id'],u));d.execute('UPDATE followups SET contact_id=? WHERE contact_id=? AND user_id=?',(x['id'],y['id'],u));d.execute('INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) SELECT ?,tag_id FROM contact_tags WHERE contact_id=?',(x['id'],y['id']));d.execute('DELETE FROM contact_tags WHERE contact_id=?',(y['id'],));d.execute('INSERT OR IGNORE INTO contact_projects(contact_id,project_id) SELECT ?,project_id FROM contact_projects WHERE contact_id=?',(x['id'],y['id']));d.execute('DELETE FROM contact_projects WHERE contact_id=?',(y['id'],));d.execute('DELETE FROM contacts WHERE id=? AND user_id=?',(y['id'],u));audit(d,u,'contact.merged',x['id']);d.commit();print('Merged with confirmation')
  elif a.cmd=='export':
   rows=d.execute('SELECT id,name,email,organization,notes,created_at FROM contacts WHERE user_id=? ORDER BY id',(u,)).fetchall();records=[]
   for row in rows:
    item=dict(row);item['interactions']=[dict(x) for x in d.execute('SELECT occurred_at,note FROM interactions WHERE user_id=? AND contact_id=? ORDER BY occurred_at',(u,row['id']))];item['followups']=[dict(x) for x in d.execute('SELECT note,due_date,done FROM followups WHERE user_id=? AND contact_id=? ORDER BY due_date',(u,row['id']))]
    item['tags']=[x['name'] for x in d.execute('SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id=t.id JOIN contacts c ON c.id=ct.contact_id WHERE t.user_id=? AND c.user_id=? AND c.id=? ORDER BY t.name',(u,u,row['id']))]
    item['projects']=[x['name'] for x in d.execute('SELECT p.name FROM projects p JOIN contact_projects cp ON cp.project_id=p.id JOIN contacts c ON c.id=cp.contact_id WHERE p.user_id=? AND c.user_id=? AND c.id=? ORDER BY p.name',(u,u,row['id']))]
    records.append(item)
   if a.format=='json':
    bundle={'contacts':records,'tags':[dict(x) for x in d.execute('SELECT name FROM tags WHERE user_id=? ORDER BY name',(u,))],
            'projects':[dict(x) for x in d.execute('SELECT name,description FROM projects WHERE user_id=? ORDER BY name',(u,))],
            'organizations':[dict(x) for x in d.execute('SELECT name,notes FROM organizations WHERE user_id=? ORDER BY name',(u,))]}
    a.file.write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
   elif a.format=='csv':
    columns=['id','name','email','organization','notes','created_at','interactions_json','followups_json','tags_json','projects_json']
    with a.file.open('w',encoding='utf-8',newline='') as f:
     w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
     for item in records:w.writerow({'id':item['id'],'name':item['name'],'email':item['email'],'organization':item['organization'],'notes':item['notes'],'created_at':item['created_at'],'interactions_json':json.dumps(item['interactions'],ensure_ascii=False),'followups_json':json.dumps(item['followups'],ensure_ascii=False),'tags_json':json.dumps(item['tags'],ensure_ascii=False),'projects_json':json.dumps(item['projects'],ensure_ascii=False)})
   else:
    lines=[]
    for item in records:
     r=item;lines.append(f"- **{r['name']}** — {r['organization'] or ''}; {r['email'] or ''}; {r['notes']}\n  - Tags: "+(', '.join(item['tags']) or 'none')+"\n  - Projects: "+(', '.join(item['projects']) or 'none')+"\n  - Interactions: "+('; '.join(x['note'] for x in item['interactions']) or 'none')+"\n  - Follow-ups: "+('; '.join(f"{x['due_date']} {x['note']} {'(done)' if x['done'] else ''}" for x in item['followups']) or 'none'))
    a.file.write_text('# Contacts\n\n'+'\n'.join(lines),encoding='utf-8')
   audit(d,u,'data.exported');d.commit();print(f'Exported {len(rows)} contacts with related interactions, follow-ups, tags and projects')
  elif a.cmd=='delete-user-data':
   if not a.confirm:raise ValueError('Repeat with --confirm to delete all of this user data')
   ids=[r[0] for r in d.execute('SELECT id FROM contacts WHERE user_id=?',(u,))];d.execute('DELETE FROM audit WHERE user_id=?',(u,));d.executemany('DELETE FROM contacts WHERE id=? AND user_id=?',[(cid,u) for cid in ids]);d.execute('DELETE FROM interactions WHERE user_id=?',(u,));d.execute('DELETE FROM followups WHERE user_id=?',(u,));d.execute('DELETE FROM pending_actions WHERE user_id=?',(u,));d.execute('DELETE FROM tags WHERE user_id=?',(u,));d.execute('DELETE FROM projects WHERE user_id=?',(u,));d.execute('DELETE FROM organizations WHERE user_id=?',(u,));d.execute('DELETE FROM notification_log WHERE user_id=?',(u,));d.execute('DELETE FROM briefing_settings WHERE user_id=?',(u,));d.execute('DELETE FROM telegram_outbox WHERE chat_id=?',(u,));d.commit();print(f'Deleted {len(ids)} contact(s) and related records')
  elif a.cmd=='delete':
   owned(d,u,a.contact_id)
   if not a.confirm:raise ValueError('Repeat with --confirm to delete contact and related records')
   d.execute('DELETE FROM contacts WHERE id=? AND user_id=?',(a.contact_id,u));audit(d,u,'contact.deleted',a.contact_id);d.commit();print('Deleted contact and related records')
  elif a.cmd in ('delete-interaction','delete-followup'):
   if not a.confirm:raise ValueError('Repeat with --confirm to delete this record')
   table='interactions' if a.cmd=='delete-interaction' else 'followups';record_id=a.interaction_id if a.cmd=='delete-interaction' else a.followup_id
   row=d.execute(f'SELECT contact_id FROM {table} WHERE id=? AND user_id=?',(record_id,u)).fetchone()
   if row is None:raise ValueError('Record not found for this user')
   d.execute(f'DELETE FROM {table} WHERE id=? AND user_id=?',(record_id,u));audit(d,u,a.cmd+'.deleted',row['contact_id']);d.commit();print('Deleted')
  elif a.cmd=='tag':
   owned(d,u,a.contact_id);name=a.name.strip()
   if not name or len(name)>80:raise ValueError('Tag must contain 1–80 characters')
   d.execute('INSERT OR IGNORE INTO tags(user_id,name) VALUES(?,?)',(u,name));tag=d.execute('SELECT id FROM tags WHERE user_id=? AND name=?',(u,name)).fetchone()
   d.execute('INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) VALUES(?,?)',(a.contact_id,tag['id']));audit(d,u,'contact.tagged',a.contact_id);d.commit();print('Tag assigned')
  elif a.cmd=='untag':
   owned(d,u,a.contact_id);cur=d.execute('DELETE FROM contact_tags WHERE contact_id=? AND tag_id IN (SELECT id FROM tags WHERE user_id=? AND name=?)',(a.contact_id,u,a.name.strip()))
   if not cur.rowcount:raise ValueError('Tag is not assigned to this contact')
   d.execute('DELETE FROM tags WHERE user_id=? AND name=? AND NOT EXISTS (SELECT 1 FROM contact_tags WHERE tag_id=tags.id)',(u,a.name.strip()))
   audit(d,u,'contact.untagged',a.contact_id);d.commit();print('Tag removed')
  elif a.cmd=='tags':
   if a.contact_id is None:rows=d.execute('SELECT name,COUNT(ct.contact_id) contact_count FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id=t.id WHERE t.user_id=? GROUP BY t.id ORDER BY t.name',(u,)).fetchall()
   else:
    owned(d,u,a.contact_id);rows=d.execute('SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id=t.id WHERE t.user_id=? AND ct.contact_id=? ORDER BY t.name',(u,a.contact_id)).fetchall()
   print('\n'.join(f"{r['name']}"+(f" ({r['contact_count']} contacts)" if 'contact_count' in r.keys() else '') for r in rows) or 'No tags')
  elif a.cmd=='briefing-config':
   existing=d.execute('SELECT * FROM briefing_settings WHERE user_id=?',(u,)).fetchone()
   zone=a.timezone or (existing['timezone'] if existing else os.environ.get('CRM_TIMEZONE','Europe/Moscow'))
   try:ZoneInfo(zone)
   except (ZoneInfoNotFoundError,ValueError):raise ValueError('Timezone must be a valid IANA timezone, such as Europe/Moscow') from None
   quiet_start=a.quiet_start or (existing['quiet_start'] if existing else '22:00');quiet_end=a.quiet_end or (existing['quiet_end'] if existing else '08:00')
   from briefing_scheduler import in_quiet_hours
   in_quiet_hours(datetime(2026,1,1,12,0,tzinfo=ZoneInfo(zone)),quiet_start,quiet_end)
   stale_days=a.stale_days if a.stale_days is not None else (existing['stale_days'] if existing else 90)
   if not 1<=stale_days<=3650:raise ValueError('Stale-days must be between 1 and 3650')
   enabled=int(a.enabled if a.enabled is not None else (existing['enabled'] if existing else 0))
   d.execute('''INSERT INTO briefing_settings(user_id,timezone,quiet_start,quiet_end,stale_days,enabled) VALUES(?,?,?,?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone,quiet_start=excluded.quiet_start,quiet_end=excluded.quiet_end,stale_days=excluded.stale_days,enabled=excluded.enabled''',(u,zone,quiet_start,quiet_end,stale_days,enabled));d.commit()
   print(json.dumps({'user_id':u,'timezone':zone,'quiet_hours':[quiet_start,quiet_end],'stale_days':stale_days,'enabled':bool(enabled)},ensure_ascii=False))
  elif a.cmd=='dispatch-briefings':
   from briefing_scheduler import enqueue_due_briefings
   count=enqueue_due_briefings(d);print(f'Queued {count} briefing(s). No messages were sent; active bot polling delivers the persisted outbox.')
  elif a.cmd=='delivery-status':
   rows=d.execute('SELECT id,status,attempt_count,created_at,sent_at,dedupe_key FROM telegram_outbox WHERE chat_id=? ORDER BY id DESC LIMIT 100',(u,)).fetchall()
   print(json.dumps([dict(r) for r in rows],ensure_ascii=False,indent=2))
  elif a.cmd=='retry-delivery':
   if not a.confirm:raise ValueError('Repeat with --confirm to retry a definite failed delivery')
   cur=d.execute("UPDATE telegram_outbox SET status='queued' WHERE id=? AND chat_id=? AND status='failed' AND attempt_count<?",(a.delivery_id,u,MAX_DELIVERY_ATTEMPTS))
   if cur.rowcount!=1:raise ValueError('Delivery is not a retryable failed item belonging to this user, or its retry limit was reached')
   d.commit();print('Delivery queued for one retry by the bot process')
 except (ValueError,sqlite3.IntegrityError) as e: p.error(str(e))
 finally:d.close()
if __name__=='__main__':main()

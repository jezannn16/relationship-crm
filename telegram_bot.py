"""Telegram capture and CRM commands; every operation is scoped to the allowlisted sender."""
from __future__ import annotations
import json,os,re
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

CAPTURE_RE=re.compile(r'(?i)(?:встретил(?:ся|ась)? с|поговорил(?:а)? с|met with|talked to)\s+(?P<name>[^,]+?)(?:\s+(?:из\s+(?:компании\s+)?|from\s+)(?P<org>[^,]+?))?,\s*(?:обсудили|обсудил[аи]?|discussed)\s+(?P<note>[^,]+?)(?:,\s*(?:написать|напомнить|follow[- ]?up)\s+(?P<due>[^,]+))?$')
WEEKDAYS={'понедельник':0,'вторник':1,'среду':2,'среда':2,'четверг':3,'пятницу':4,'пятница':4,'субботу':5,'суббота':5,'воскресенье':6,'monday':0,'tuesday':1,'wednesday':2,'thursday':3,'friday':4,'saturday':5,'sunday':6}

def _zone():
 try:return ZoneInfo(os.environ.get('CRM_TIMEZONE','Europe/Moscow'))
 except ZoneInfoNotFoundError:return timezone.utc

def _due(value):
 value=(value or '').strip().lower()
 try:return date.fromisoformat(value).isoformat()
 except ValueError:pass
 target=WEEKDAYS.get(value.removeprefix('в ').removeprefix('on '))
 if target is None:return None
 today=datetime.now(_zone()).date();days=(target-today.weekday())%7 or 7
 return (today+timedelta(days=days)).isoformat()

def _user_ids():return {x.strip() for x in os.environ.get('CRM_ALLOWED_USER_IDS','').split(',') if x.strip()}
def _audit(db,user,event,eid=None):db.execute('INSERT INTO audit(user_id,event,entity_id,created_at) VALUES(?,?,?,?)',(user,event,eid,datetime.now(timezone.utc).isoformat()))
def _owned(db,user,cid):
 row=db.execute('SELECT * FROM contacts WHERE id=? AND user_id=?',(cid,user)).fetchone()
 if row is None:raise ValueError('Contact not found')
 return row

def _search(db,user,text):
 pat='%'+text+'%'
 return db.execute('SELECT c.id,c.name,c.organization,max(i.occurred_at) last_contact FROM contacts c LEFT JOIN interactions i ON i.contact_id=c.id AND i.user_id=c.user_id WHERE c.user_id=? AND (c.name LIKE ? OR c.organization LIKE ? OR c.email LIKE ?) GROUP BY c.id ORDER BY c.name LIMIT 20',(user,pat,pat,pat)).fetchall()

def handle_update(update,db):
 msg=update.get('message') or {};sender=msg.get('from') or {};chat=msg.get('chat') or {};uid=str(sender.get('id',''));chat_id=chat.get('id');text=str(msg.get('text','')).strip()
 if not uid or chat.get('type')!='private' or not text:return []
 if uid not in _user_ids():return [(chat_id,'Access is not enabled for this Telegram account.')]
 if len(text)>3000:return [(chat_id,'Message is too long. Keep it under 3000 characters.')]
 parts=text.split(maxsplit=1);command=parts[0].split('@',1)[0].lower();arg=parts[1].strip() if len(parts)>1 else ''
 if command in ('/start','/help'):
  return [(chat_id,'Relationship CRM commands: /contacts, /search NAME, /capture <meeting note>, /confirm, /cancel, /add NAME | EMAIL | ORG, /log ID NOTE, /followup ID YYYY-MM-DD NOTE, /history ID, /briefing, /done FOLLOWUP_ID, /tag ID TAG, /untag ID TAG, /tags [ID], /project ID NAME, /duplicates ID, /merge KEEP REMOVE, /delete ID, /export. Dates are in CRM_TIMEZONE. Messages are never sent to contacts.')]
 if command=='/contacts':
  rows=db.execute('SELECT id,name,organization FROM contacts WHERE user_id=? ORDER BY name LIMIT 20',(uid,)).fetchall()
  return [(chat_id,'\n'.join(f"{r['id']}: {r['name']} — {r['organization'] or 'no organization'}" for r in rows) or 'No contacts yet.')]
 if command=='/search':
  rows=_search(db,uid,arg)
  return [(chat_id,'\n'.join(f"{r['id']}: {r['name']} — {r['organization'] or ''}; last contact: {r['last_contact'] or 'never'}" for r in rows) or 'No matches.')]
 if command=='/add':
  fields=[x.strip() for x in arg.split('|')]
  if not fields or not fields[0]:return [(chat_id,'Usage: /add NAME | EMAIL | ORGANIZATION')]
  if len(fields)<3:fields += ['']*(3-len(fields))
  dup=db.execute('SELECT id FROM contacts WHERE user_id=? AND ((email IS NOT NULL AND lower(email)=lower(?)) OR (lower(name)=lower(?) AND lower(coalesce(organization,""))=lower(?)))',(uid,fields[1],fields[0],fields[2])).fetchall()
  cur=db.execute('INSERT INTO contacts(user_id,name,email,organization,notes,created_at) VALUES(?,?,?,?,?,?)',(uid,fields[0],fields[1] or None,fields[2] or None,'',datetime.now(timezone.utc).isoformat()));_audit(db,uid,'contact.created',cur.lastrowid)
  suggestion=', possible duplicates: '+', '.join(str(r['id']) for r in dup) if dup else ''
  return [(chat_id,f'Contact #{cur.lastrowid} created{suggestion}.')]
 if command=='/capture':
  m=CAPTURE_RE.fullmatch(arg)
  if not m:return [(chat_id,'I could not safely parse this. Use: /capture Met with NAME from COMPANY, discussed TOPIC, follow-up Friday (or an ISO date).')]
  due=_due(m.group('due'))
  if not due:return [(chat_id,'Please provide an unambiguous follow-up date such as 2026-11-05 or a weekday name.')]
  action={'kind':'capture','name':m.group('name').strip(),'org':(m.group('org') or '').strip(),'note':m.group('note').strip(),'due':due}
  db.execute('INSERT INTO pending_actions(user_id,action_json,created_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET action_json=excluded.action_json,created_at=excluded.created_at',(uid,json.dumps(action,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
  return [(chat_id,f"Please confirm: contact {action['name']} ({action['org'] or 'no organization'}); note: {action['note']}; follow-up {due} in {os.environ.get('CRM_TIMEZONE','Europe/Moscow')}. Send /confirm or /cancel.")]
 if command=='/confirm':
  pending=db.execute('SELECT action_json FROM pending_actions WHERE user_id=?',(uid,)).fetchone()
  if not pending:return [(chat_id,'There is no pending action to confirm.')]
  action=json.loads(pending['action_json'])
  if action.get('kind')=='capture':
   row=db.execute('SELECT id FROM contacts WHERE user_id=? AND lower(name)=lower(?) AND lower(coalesce(organization,""))=lower(?) ORDER BY id LIMIT 1',(uid,action['name'],action['org'])).fetchone()
   if row:cid=row['id']
   else:
    cur=db.execute('INSERT INTO contacts(user_id,name,organization,created_at) VALUES(?,?,?,?)',(uid,action['name'],action['org'] or None,datetime.now(timezone.utc).isoformat()));cid=cur.lastrowid;_audit(db,uid,'contact.created',cid)
   db.execute('INSERT INTO interactions(user_id,contact_id,note,occurred_at) VALUES(?,?,?,?)',(uid,cid,action['note'],datetime.now(timezone.utc).isoformat()))
   db.execute('INSERT INTO followups(user_id,contact_id,note,due_date) VALUES(?,?,?,?)',(uid,cid,'Follow up: '+action['note'],action['due']));_audit(db,uid,'capture.confirmed',cid)
   out=f"Saved interaction for {action['name']} and follow-up {action['due']} (contact #{cid})."
  elif action.get('kind')=='merge':
   keep,remove=action['keep'],action['remove'];_owned(db,uid,keep);_owned(db,uid,remove)
   db.execute('UPDATE interactions SET contact_id=? WHERE contact_id=? AND user_id=?',(keep,remove,uid));db.execute('UPDATE followups SET contact_id=? WHERE contact_id=? AND user_id=?',(keep,remove,uid))
   db.execute('INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) SELECT ?,tag_id FROM contact_tags WHERE contact_id=?',(keep,remove));db.execute('DELETE FROM contact_tags WHERE contact_id=?',(remove,))
   db.execute('INSERT OR IGNORE INTO contact_projects(contact_id,project_id) SELECT ?,project_id FROM contact_projects WHERE contact_id=?',(keep,remove));db.execute('DELETE FROM contact_projects WHERE contact_id=?',(remove,))
   db.execute('DELETE FROM contacts WHERE id=? AND user_id=?',(remove,uid));_audit(db,uid,'contact.merged',keep);out=f'Contact #{remove} merged into #{keep}.'
  elif action.get('kind')=='delete':
   cid=action['id'];_owned(db,uid,cid);db.execute('DELETE FROM contacts WHERE id=? AND user_id=?',(cid,uid));_audit(db,uid,'contact.deleted',cid);out=f'Contact #{cid} and related records deleted.'
  else:return [(chat_id,'Pending action type is unsupported; cancel it and try again.')]
  db.execute('DELETE FROM pending_actions WHERE user_id=?',(uid,));return [(chat_id,out)]
 if command=='/cancel':
  db.execute('DELETE FROM pending_actions WHERE user_id=?',(uid,));return [(chat_id,'Pending action cancelled.')]
 if command=='/history':
  try:cid=int(arg)
  except ValueError:return [(chat_id,'Usage: /history CONTACT_ID')]
  try:_owned(db,uid,cid)
  except ValueError:return [(chat_id,'Contact not found.')]
  rows=db.execute('SELECT occurred_at,note FROM interactions WHERE user_id=? AND contact_id=? ORDER BY occurred_at DESC LIMIT 10',(uid,cid)).fetchall()
  return [(chat_id,'\n'.join(f"{r['occurred_at']}: {r['note']}" for r in rows) or 'No interactions.')]
 if command=='/log':
  bits=arg.split(maxsplit=1)
  if len(bits)!=2 or not bits[1]:return [(chat_id,'Usage: /log CONTACT_ID NOTE')]
  try:cid=int(bits[0]);_owned(db,uid,cid)
  except (ValueError,TypeError):return [(chat_id,'Contact not found or invalid ID.')]
  db.execute('INSERT INTO interactions(user_id,contact_id,note,occurred_at) VALUES(?,?,?,?)',(uid,cid,bits[1],datetime.now(timezone.utc).isoformat()));_audit(db,uid,'interaction.created',cid);return [(chat_id,'Interaction saved.')]
 if command=='/followup':
  bits=arg.split(maxsplit=2)
  if len(bits)!=3:return [(chat_id,'Usage: /followup CONTACT_ID YYYY-MM-DD NOTE')]
  try:cid=int(bits[0]);_owned(db,uid,cid);due=date.fromisoformat(bits[1]).isoformat()
  except (ValueError,TypeError):return [(chat_id,'Contact or date is invalid. Use YYYY-MM-DD.')]
  db.execute('INSERT INTO followups(user_id,contact_id,note,due_date) VALUES(?,?,?,?)',(uid,cid,bits[2],due));_audit(db,uid,'followup.created',cid);return [(chat_id,'Follow-up saved.')]
 if command=='/done':
  try:fid=int(arg)
  except ValueError:return [(chat_id,'Usage: /done FOLLOWUP_ID')]
  cur=db.execute('UPDATE followups SET done=1 WHERE id=? AND user_id=?',(fid,uid));return [(chat_id,'Follow-up marked complete.' if cur.rowcount else 'Follow-up not found.')]
 if command in ('/followups','/briefing'):
  bits=arg.split()
  try:stale_days=int(bits[0]) if bits else 90
  except ValueError:return [(chat_id,'Usage: /briefing [stale-days, default 90]')]
  if stale_days<1 or stale_days>3650:return [(chat_id,'Stale-days must be between 1 and 3650.')]
  today=datetime.now(_zone()).date();today_text=today.isoformat();cutoff=(today-timedelta(days=stale_days)).isoformat()
  rows=db.execute('SELECT f.id,c.name,f.note,f.due_date FROM followups f JOIN contacts c ON c.id=f.contact_id WHERE f.user_id=? AND c.user_id=? AND f.done=0 AND f.due_date<=? ORDER BY f.due_date LIMIT 20',(uid,uid,today_text)).fetchall()
  stale=db.execute('''SELECT c.id,c.name,COALESCE(MAX(i.occurred_at),c.created_at) AS last_contact
    FROM contacts c LEFT JOIN interactions i ON i.contact_id=c.id AND i.user_id=c.user_id
    WHERE c.user_id=? GROUP BY c.id HAVING substr(last_contact,1,10)<=? ORDER BY last_contact LIMIT 20''',(uid,cutoff)).fetchall()
  due_lines=[f"#{r['id']} {r['due_date']} {r['name']}: {r['note']}" for r in rows]
  stale_lines=[f"#{r['id']} {r['name']}: last interaction {r['last_contact'][:10]}" for r in stale]
  sections=[f'Follow-ups due or overdue:\n{chr(10).join(due_lines) if due_lines else "None"}',f'No interaction in {stale_days}+ days:\n{chr(10).join(stale_lines) if stale_lines else "None"}']
  return [(chat_id,'\n\n'.join(sections)[:3900])]
 if command in ('/tag','/project','/untag'):
  bits=arg.split(maxsplit=1)
  if len(bits)!=2:return [(chat_id,f'Usage: {command} CONTACT_ID NAME')]
  try:cid=int(bits[0]);_owned(db,uid,cid)
  except ValueError:return [(chat_id,'Contact not found.')]
  if command=='/tag':
   db.execute('INSERT OR IGNORE INTO tags(user_id,name) VALUES(?,?)',(uid,bits[1]));tag=db.execute('SELECT id FROM tags WHERE user_id=? AND name=?',(uid,bits[1])).fetchone()[0];db.execute('INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) VALUES(?,?)',(cid,tag))
  elif command=='/untag':
   cur=db.execute('DELETE FROM contact_tags WHERE contact_id=? AND tag_id IN (SELECT id FROM tags WHERE user_id=? AND name=?)',(cid,uid,bits[1]))
   if not cur.rowcount:return [(chat_id,'That tag is not assigned to this contact.')]
   db.execute('DELETE FROM tags WHERE user_id=? AND name=? AND NOT EXISTS (SELECT 1 FROM contact_tags WHERE tag_id=tags.id)',(uid,bits[1]))
  else:
   from app import create_project,assign_project
   if not db.execute('SELECT 1 FROM projects WHERE user_id=? AND lower(name)=lower(?)',(uid,bits[1].strip())).fetchone():create_project(db,uid,bits[1])
   try:assign_project(db,uid,cid,bits[1])
   except ValueError as exc:return [(chat_id,str(exc))]
  _audit(db,uid,'contact.'+command[1:],cid);return [(chat_id,f'{command[1:]} saved.')]
 if command=='/tags':
  bits=arg.split()
  if bits:
   try:cid=int(bits[0]);_owned(db,uid,cid)
   except (ValueError,TypeError):return [(chat_id,'Contact not found.')]
   rows=db.execute('SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id=t.id WHERE t.user_id=? AND ct.contact_id=? ORDER BY t.name',(uid,cid)).fetchall()
  else:rows=db.execute('SELECT name FROM tags WHERE user_id=? ORDER BY name',(uid,)).fetchall()
  return [(chat_id,'\n'.join(r['name'] for r in rows) or 'No tags.')]
 if command=='/duplicates':
  try:cid=int(arg);c=_owned(db,uid,cid)
  except ValueError:return [(chat_id,'Contact not found.')]
  rows=db.execute('SELECT id,name,email,organization FROM contacts WHERE user_id=? AND id<>? AND (lower(name)=lower(?) OR (email IS NOT NULL AND lower(email)=lower(?)) OR (organization IS NOT NULL AND lower(organization)=lower(?)))',(uid,cid,c['name'],c['email'] or '',c['organization'] or '')).fetchall()
  body='Possible duplicates (review before merge):\n'+'\n'.join(f"#{r['id']} {r['name']} / {r['email'] or ''} / {r['organization'] or ''}" for r in rows) if rows else 'No likely duplicates.'
  return [(chat_id,body)]
 if command in ('/merge','/delete'):
  bits=arg.split()
  if command=='/merge' and len(bits)==2:
   try:keep,remove=map(int,bits);_owned(db,uid,keep);_owned(db,uid,remove)
   except (ValueError,TypeError):return [(chat_id,'Two contact IDs belonging to you are required.')]
   if keep==remove:return [(chat_id,'Choose two different contacts.')]
   action={'kind':'merge','keep':keep,'remove':remove}
  elif command=='/delete' and len(bits)==1:
   try:cid=int(bits[0]);_owned(db,uid,cid)
   except (ValueError,TypeError):return [(chat_id,'Contact not found.')]
   action={'kind':'delete','id':cid}
  else:return [(chat_id,'Usage: /merge KEEP_ID REMOVE_ID or /delete CONTACT_ID')]
  db.execute('INSERT INTO pending_actions(user_id,action_json,created_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET action_json=excluded.action_json,created_at=excluded.created_at',(uid,json.dumps(action),datetime.now(timezone.utc).isoformat()))
  return [(chat_id,'Please review and send /confirm or /cancel.')]
 if command=='/export':
  rows=db.execute('SELECT id,name,email,organization,notes FROM contacts WHERE user_id=? ORDER BY id LIMIT 50',(uid,)).fetchall()
  body=('Your contacts (CSV-style):\n'+'\n'.join(f"{r['id']},{r['name']},{r['email'] or ''},{r['organization'] or ''},{r['notes']}" for r in rows))[:3900] if rows else 'No contacts.'
  return [(chat_id,body)]
 return [(chat_id,'Unknown command. Send /help.')]

def start_bot(db_path):
 import os
 from app import connect
 from telegram_api import TelegramAPI
 from telegram_runtime import run_polling
 token=os.environ.get('TELEGRAM_BOT_TOKEN','')
 if not os.environ.get('CRM_ALLOWED_USER_IDS','').strip():raise SystemExit('Set CRM_ALLOWED_USER_IDS in the process environment before starting.')
 api=TelegramAPI(token);db=connect(db_path)
 try:run_polling(db,api,handle_update)
 finally:db.close()

def main():
 import argparse
 parser=argparse.ArgumentParser(description='Relationship CRM Telegram bot');parser.add_argument('--db',default='crm.sqlite3');args=parser.parse_args();start_bot(args.db)
if __name__=='__main__':main()

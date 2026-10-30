import tempfile
import unittest
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import app
from briefing_scheduler import enqueue_due_briefings, in_quiet_hours
from telegram_api import TelegramAPIError, TelegramDeliveryUncertain
from telegram_runtime import flush_outbox


class FakeAPI:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def send_message(self, chat, text):
        if self.error:
            raise self.error
        self.sent.append((str(chat), text))


class BriefingSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = app.connect(Path(self.tmp.name) / 'crm.sqlite3')
        self.db.execute('''INSERT INTO briefing_settings(user_id,timezone,quiet_start,quiet_end,stale_days,enabled)
            VALUES('101','Europe/Moscow','22:00','08:00',30,1)''')
        self.db.execute('INSERT INTO contacts(user_id,name,created_at) VALUES(?,?,?)',
                        ('101', 'Synthetic follow-up contact', '2020-01-01T00:00:00+00:00'))
        self.db.execute('INSERT INTO followups(user_id,contact_id,note,due_date) VALUES(?,?,?,?)',
                        ('101', 1, 'Synthetic overdue action', '2020-01-02'))
        self.db.execute('''INSERT INTO briefing_settings(user_id,timezone,quiet_start,quiet_end,stale_days,enabled)
            VALUES('202','UTC','22:00','08:00',30,0)''')
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_local_timezone_quiet_hours_and_daily_dedup_queue_without_sending(self):
        before_quiet_end = datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc)  # 07:00 Moscow
        after_quiet_end = datetime(2026, 10, 30, 5, 0, tzinfo=timezone.utc)  # 08:00 Moscow
        self.assertTrue(in_quiet_hours(before_quiet_end.astimezone(ZoneInfo('Europe/Moscow')), '22:00', '08:00'))
        self.assertEqual(enqueue_due_briefings(self.db, before_quiet_end), 0)
        self.assertEqual(enqueue_due_briefings(self.db, after_quiet_end), 1)
        self.assertEqual(enqueue_due_briefings(self.db, after_quiet_end), 0)
        row = self.db.execute("SELECT * FROM telegram_outbox WHERE chat_id='101'").fetchone()
        self.assertEqual(row['status'], 'queued')
        self.assertEqual(row['notification_key'], 'daily-briefing:2026-10-30')
        self.assertIn('Synthetic overdue action', row['text'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM telegram_outbox WHERE chat_id="202"').fetchone()[0], 0)

    def test_delivery_is_persisted_failure_and_uncertain_results_are_not_retried(self):
        instant = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
        enqueue_due_briefings(self.db, instant)
        api = FakeAPI(TelegramAPIError('definite synthetic failure'))
        flush_outbox(self.db, api)
        row = self.db.execute('SELECT id,status,attempt_count FROM telegram_outbox WHERE chat_id="101"').fetchone()
        self.assertEqual((row['status'], row['attempt_count']), ('failed', 1))
        api = FakeAPI(TelegramDeliveryUncertain('synthetic timeout'))
        self.db.execute("UPDATE telegram_outbox SET status='queued' WHERE id=?", (row['id'],))
        self.db.commit()
        flush_outbox(self.db, api)
        self.assertEqual(tuple(self.db.execute('SELECT status,attempt_count FROM telegram_outbox WHERE id=?',
                                               (row['id'],)).fetchone()), ('uncertain', 2))
        self.assertEqual(api.sent, [])

    def test_queued_briefing_survives_restart_and_success_blocks_redelivery(self):
        instant = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
        enqueue_due_briefings(self.db, instant)
        path = Path(self.tmp.name) / 'crm.sqlite3'
        self.db.close()
        self.db = app.connect(path)
        row = self.db.execute("SELECT id,status FROM telegram_outbox WHERE chat_id='101'").fetchone()
        self.assertEqual(row['status'], 'queued')
        api = FakeAPI()
        flush_outbox(self.db, api)
        self.assertEqual(len(api.sent), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM notification_log WHERE user_id="101"').fetchone()[0], 1)
        self.assertEqual(enqueue_due_briefings(self.db, instant), 0)

    def test_manual_retry_is_owner_scoped_and_bounded(self):
        self.db.execute("INSERT INTO telegram_outbox(update_id,sequence,chat_id,text,status,created_at,attempt_count) VALUES(301,0,'101','synthetic','failed','now',3)")
        self.db.execute("INSERT INTO telegram_outbox(update_id,sequence,chat_id,text,status,created_at,attempt_count) VALUES(302,0,'101','synthetic','failed','now',1)")
        self.db.commit()
        def cli(user, delivery):
            return subprocess.run([sys.executable,'app.py','--db',str(Path(self.tmp.name)/'crm.sqlite3'),
                '--user',user,'retry-delivery',str(delivery),'--confirm'],capture_output=True,text=True)
        self.assertNotEqual(cli('101',1).returncode,0)
        self.assertNotEqual(cli('202',2).returncode,0)
        self.assertEqual(cli('101',2).returncode,0)
        self.assertEqual(self.db.execute('SELECT status FROM telegram_outbox WHERE id=2').fetchone()[0],'queued')


if __name__ == '__main__':
    unittest.main()

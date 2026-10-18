import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import mailer
import draftbox


class DraftBoxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = mailer.database(Path(self.tmp.name)/'test.db')
        self.addCleanup(self.db.close)
        self.c = dict(account='account@qq.com', name='Tester', sender='sender@foxmail.com')
        msg = mailer.message(self.c, 'recipient@example.org', 'Draft test', 'Body')
        self.d = dict(id='test-draft', account=self.c['account'], raw=msg.as_bytes().decode('ascii'),
                      recipient='recipient@example.org', resume='', attachment_hash='', unit='test', role='test', kind='mail')

    def test_append_is_draft_only_and_read_back(self):
        box = MagicMock()
        box.client.select.return_value = ('OK', [b'1'])
        box.client.append.return_value = ('OK', [b'APPEND completed'])
        box.client.uid.side_effect = [('OK', [b'23']), ('OK', [(b'1 (UID 23 FLAGS (\\Draft) BODY[] {100}', self.d['raw'].encode('ascii'))])]
        result = draftbox.append_and_verify(box, self.d['raw'])
        self.assertTrue(result['verified'])
        self.assertEqual(box.client.append.call_args.args[:2], ('Drafts', r'(\Draft)'))
        box.client.select.assert_called_with('Drafts', readonly=True)
        self.assertIn('BODY.PEEK[]', box.client.uid.call_args.args[2])

    def test_decline_never_connects(self):
        with patch('builtins.input', return_value='NO'), patch.object(draftbox, 'Mailbox') as connect, patch('sys.stdout'):
            draftbox.save_draft(self.db, self.c, self.d)
        connect.assert_not_called()

    def test_saved_and_uncertain_attempts_block_duplicates(self):
        for status in ('已保存', '结果不明', '保存中'):
            with self.subTest(status=status):
                self.db.execute('DELETE FROM remote_drafts')
                self.db.execute('INSERT INTO remote_drafts(account,draft_id,status) VALUES (?,?,?)', (self.c['account'], self.d['id'], status))
                self.db.commit()
                with patch('builtins.input', return_value='保存草稿 test-draft'), patch.object(draftbox, 'Mailbox') as connect, patch('sys.stdout'):
                    draftbox.save_draft(self.db, self.c, self.d)
                connect.assert_not_called()

    def test_append_timeout_is_uncertain_and_not_retried(self):
        box = MagicMock()
        box.client.select.return_value = ('OK', [b'1'])
        box.client.append.side_effect = TimeoutError()
        with self.assertRaises(draftbox.DraftSaveError) as caught:
            draftbox.append_and_verify(box, self.d['raw'])
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(box.client.append.call_count, 1)

    def test_interruption_after_acceptance_still_blocks_reappend(self):
        box = MagicMock()
        box.client.select.return_value = ('OK', [b'1'])
        box.client.append.return_value = ('OK', [b'saved'])
        box.client.uid.side_effect = KeyboardInterrupt()
        result = draftbox.append_and_verify(box, self.d['raw'])
        self.assertTrue(result['accepted'])
        self.assertFalse(result['verified'])
        self.assertEqual(box.client.append.call_count, 1)

    def test_rejected_append_is_safe_failure(self):
        box = MagicMock()
        box.client.select.return_value = ('OK', [b'1'])
        box.client.append.return_value = ('NO', [b'rejected'])
        with self.assertRaises(draftbox.DraftSaveError) as caught:
            draftbox.append_and_verify(box, self.d['raw'])
        self.assertFalse(caught.exception.uncertain)

    def test_unexpected_interruption_is_not_retryable(self):
        with patch('builtins.input', return_value='保存草稿 test-draft'), patch.object(draftbox, 'Mailbox'), patch.object(draftbox, 'append_and_verify', side_effect=KeyboardInterrupt()), patch('sys.stdout'):
            draftbox.save_draft(self.db, self.c, self.d)
        status = self.db.execute('SELECT status FROM remote_drafts WHERE draft_id=?', (self.d['id'],)).fetchone()[0]
        self.assertEqual(status, '结果不明')

    def test_readback_failure_does_not_repeat_accepted_append(self):
        box = MagicMock()
        box.client.select.return_value = ('OK', [b'1'])
        box.client.append.return_value = ('OK', [b'saved'])
        box.client.uid.side_effect = TimeoutError()
        result = draftbox.append_and_verify(box, self.d['raw'])
        self.assertFalse(result['verified'])
        self.assertEqual(box.client.append.call_count, 1)


if __name__ == '__main__': unittest.main()

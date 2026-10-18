import tempfile
import unittest
from pathlib import Path
from email.message import EmailMessage
from unittest.mock import MagicMock, patch
import inbox


def sample():
    m = EmailMessage()
    m['From'] = 'Sender <sender@example.org>'
    m['Reply-To'] = 'reply@example.org'
    m['To'] = 'recipient@example.org'
    m['Subject'] = '中文测试'
    m['Message-ID'] = '<original@example.org>'
    m.set_content('你好，这是正文。')
    m.add_attachment(b'attachment-data', maintype='application', subtype='octet-stream', filename='../CON.txt')
    return m.as_bytes()


class InboxTests(unittest.TestCase):
    def client(self):
        box = inbox.Mailbox({'account': 'account@qq.com'})
        box.client = MagicMock()
        box.validity = '77'
        return box

    def test_connection_is_readonly_and_secret_not_returned(self):
        client = MagicMock()
        client.capabilities = (b'IMAP4rev1', b'ID')
        client.select.return_value = ('OK', [b'2'])
        client.response.return_value = ('UIDVALIDITY', [b'77'])
        with patch.object(inbox.imaplib, 'IMAP4_SSL', return_value=client), patch.object(inbox.wincred, 'get', return_value='dummy') as get:
            with inbox.Mailbox({'account':'account@qq.com'}) as box:
                self.assertEqual(box.validity, '77')
            client.select.assert_called_once_with('INBOX', readonly=True)
            get.assert_called_once_with('account@qq.com')
            client.logout.assert_called_once()
            self.assertTrue(client.login.called)

    def test_list_uses_uids_peek_and_decodes_chinese(self):
        box = self.client()
        box.client.uid.side_effect = [('OK', [b'3 12']), ('OK', [(b'1 (UID 12 FLAGS () BODY[HEADER] {100}', sample()), b')', (b'2 (UID 3 FLAGS (\\Seen) BODY[HEADER] {100}', sample()), b')'])]
        result = box.list_messages(limit=2)
        self.assertEqual([x['id'] for x in result['messages']], ['77:12', '77:3'])
        self.assertEqual(result['messages'][0]['subject'], '中文测试')
        self.assertTrue(result['messages'][0]['unread'])
        self.assertFalse(result['messages'][1]['unread'])
        self.assertIn('BODY.PEEK[', box.client.uid.call_args.args[2])

    def test_subject_search_and_scan_limit_are_explicit(self):
        box = self.client()
        box.client.uid.side_effect = [('OK', [b' '.join(str(i).encode() for i in range(1, 505))])] + [('OK', [])] * 10
        result = box.list_messages(subject='中文', since='2026-01-01', unread=True)
        self.assertTrue(result['search_truncated'])
        self.assertEqual(result['scanned'], 500)
        self.assertEqual(box.client.uid.call_args_list[0].args, ('SEARCH', None, 'UNSEEN', 'SINCE', '01-Jan-2026'))

    def test_stale_reference_is_rejected_before_fetch(self):
        box = self.client()
        with self.assertRaises(ValueError): box.read_message('76:12')
        box.client.uid.assert_not_called()

    def test_read_uses_peek_and_lists_attachments(self):
        box = self.client()
        box.client.uid.side_effect = [('OK', [(b'1 (RFC822.SIZE 1000)', b'')]), ('OK', [(b'1 (BODY[] {1000}', sample())])]
        result = box.read_message('77:12')
        self.assertIn('你好', result['body'])
        self.assertEqual(len(result['attachments']), 1)
        self.assertIn('BODY.PEEK[]', box.client.uid.call_args.args[2])

    def test_download_sanitizes_name_and_never_overwrites(self):
        box = self.client()
        with tempfile.TemporaryDirectory() as tmp, patch.object(box, '_message', return_value=inbox.parse(sample())):
            first = box.download('77:12', 1, Path(tmp))
            second = box.download('77:12', 1, Path(tmp))
            self.assertNotEqual(first['path'], second['path'])
            self.assertEqual(Path(first['path']).parent, Path(tmp).resolve())
            self.assertFalse(Path(first['path']).name.upper().startswith('CON.'))
            self.assertEqual(Path(first['path']).read_bytes(), b'attachment-data')
            with self.assertRaises(ValueError): box.download('77:12', 0, Path(tmp))

    def test_reply_uses_reply_to_and_thread_headers(self):
        spec = inbox.reply_spec(inbox.parse(sample()), '回复正文')
        self.assertEqual(spec['to'], 'reply@example.org')
        self.assertEqual(spec['in_reply_to'], '<original@example.org>')
        self.assertIn('<original@example.org>', spec['references'])
        self.assertTrue(spec['subject'].startswith('Re:'))
        self.assertIn('回复正文', spec['body'])

    def test_attached_email_is_one_file_not_its_nested_files(self):
        inner = inbox.parse(sample())
        outer = EmailMessage()
        outer.set_content('See attached message')
        outer.add_attachment(inner, filename='forwarded.eml')
        msg = inbox.parse(outer.as_bytes())
        files = inbox.attachment_list(msg)
        self.assertEqual([x['filename'] for x in files], ['forwarded.eml'])
        box = self.client()
        with tempfile.TemporaryDirectory() as tmp, patch.object(box, '_message', return_value=msg):
            result = box.download('77:12', 1, Path(tmp))
            downloaded = inbox.parse(Path(result['path']).read_bytes())
            self.assertEqual(downloaded['Subject'], '中文测试')

    def test_html_only_is_text_without_running_or_loading(self):
        m = EmailMessage()
        m.set_content('<html><script>bad()</script><p>Hello &amp; world</p><img src="https://example.org/pixel"></html>', subtype='html')
        body = inbox.body_text(m)
        self.assertIn('Hello & world', body)
        self.assertNotIn('bad()', body)
        self.assertNotIn('pixel', body)

    def test_oversize_is_rejected_before_body_fetch(self):
        box = self.client()
        box.client.uid.return_value = ('OK', [b'1 (RFC822.SIZE 999999999)'])
        with self.assertRaises(ValueError): box.read_message('77:12')
        self.assertEqual(box.client.uid.call_count, 1)

    def test_search_dates_reject_injection(self):
        box = self.client()
        with self.assertRaises(ValueError): box.list_messages(since='2026-01-01) ALL')
        box.client.uid.assert_not_called()


if __name__ == '__main__': unittest.main()

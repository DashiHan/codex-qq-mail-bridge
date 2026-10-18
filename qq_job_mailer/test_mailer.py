import tempfile
import unittest
import csv
import contextlib
import io
from pathlib import Path
from unittest.mock import patch
import mailer as m


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        root_patch = patch.object(m, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        output_patch = contextlib.redirect_stdout(io.StringIO())
        output_patch.__enter__()
        self.addCleanup(output_patch.__exit__, None, None, None)
        import shutil
        shutil.copytree(Path(__file__).parent / 'templates', self.root / 'templates')
        self.pdf = self.root / '中文简历.pdf'
        self.pdf.write_bytes(b'%PDF-1.4\n test')
        self.cfg = {'account': '123@qq.com', 'name': '测试者', 'phone': '',
                    'profile': '研究方向与个人简介示例。',
                    'resumes': {k: str(self.pdf) for k in m.KINDS}, 'interval': 60}
        self.db = m.database(self.root / 'test.db')
        self.addCleanup(self.db.close)

    def draft(self, email='hr@example.org'):
        return m.make_draft(self.cfg, {'单位':'测试单位', '岗位':'科研岗',
            '性质':'高校', '联系人':'张老师', '邮箱':email, '简历路径':''}, self.root)

    def test_foxmail_sender_keeps_login_account(self):
        self.cfg['sender'] = 'sender@foxmail.com'
        d = self.draft()
        msg = m.parse(d['raw'])
        self.assertEqual(msg['From'].addresses[0].addr_spec, self.cfg['sender'])
        self.assertIn(self.cfg['sender'], msg.get_body().get_content())
        with patch.object(m.wincred, 'get', return_value='dummy-test-only') as credential, patch.object(m.smtplib, 'SMTP_SSL') as client:
            client.return_value.send_message.return_value = {}
            m.deliver(self.cfg, d)
            credential.assert_called_once_with(self.cfg['account'])
            self.assertEqual(client.return_value.login.call_args.args[0], self.cfg['account'])
            self.assertEqual(client.return_value.send_message.call_args.kwargs['from_addr'], self.cfg['sender'])

    def test_old_sender_draft_rejected_after_switch(self):
        d = self.draft(self.cfg['account'])
        self.cfg['sender'] = 'sender@foxmail.com'
        with patch.object(m, 'deliver') as send, self.assertRaises(ValueError):
            m.review_send(self.db, self.cfg, d, test=True)
        send.assert_not_called()

    def general_spec(self):
        image = self.root / 'inline.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'test')
        attachment = self.root / '说明.txt'
        attachment.write_text('中文附件测试', encoding='utf-8')
        return dict(to='recipient@example.org', subject='图片与附件测试',
                    body='正文图片测试', html='<p>正文图片测试</p><img src="cid:test-image">',
                    inline_images=[dict(path=str(image), cid='test-image')],
                    attachments=[str(attachment)])

    def test_general_mime_inline_and_attachment(self):
        spec = self.general_spec()
        d = m.make_mail_draft(self.cfg, spec, self.root)
        msg = m.parse(d['raw'])
        self.assertEqual(d['recipient'], spec['to'])
        self.assertIn('cid:test-image', msg.get_body(preferencelist=('html',)).get_content())
        inline = next(p for p in msg.walk() if p['Content-ID'])
        self.assertEqual(inline['Content-ID'], '<test-image>')
        self.assertEqual(inline.get_content_disposition(), 'inline')
        files = [p for p in msg.walk() if p.get_content_disposition() == 'attachment']
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].get_filename(), '说明.txt')
        self.assertEqual(files[0].get_payload(decode=True).decode('utf-8'), '中文附件测试')
        m.check_attachment(d)
        Path(spec['attachments'][0]).write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            m.check_attachment(d)

    def test_general_mail_review_gate_and_duplicate(self):
        d = m.make_mail_draft(self.cfg, self.general_spec(), self.root)
        m.save_draft(self.db, d)
        with patch.object(m, 'deliver') as send, self.assertRaises(ValueError):
            m.review_send(self.db, self.cfg, d)
        send.assert_not_called()
        self.db.execute('INSERT INTO enabled VALUES (?,?)', (self.cfg['account'], m.now()))
        self.db.commit()
        with patch('builtins.input', return_value=m.approval(d)), patch.object(m, 'deliver') as send:
            m.review_send(self.db, self.cfg, d)
        send.assert_called_once()
        another = m.make_mail_draft(self.cfg, self.general_spec(), self.root)
        self.assertEqual(d['appkey'], another['appkey'])
        self.assertFalse(m.claim(self.db, another, 0))

    def test_reply_thread_headers_are_frozen_in_saved_draft(self):
        spec = self.general_spec()
        spec['in_reply_to'] = '<original@example.org>'
        spec['references'] = '<earlier@example.org> <original@example.org>'
        d = m.make_mail_draft(self.cfg, spec, self.root)
        msg = m.parse(d['raw'])
        self.assertEqual(msg['In-Reply-To'], spec['in_reply_to'])
        self.assertEqual(msg['References'], spec['references'])
        spec['in_reply_to'] = '<different@example.org>'
        self.assertNotEqual(d['appkey'], m.make_mail_draft(self.cfg, spec, self.root)['appkey'])

    def test_non_reply_keeps_legacy_duplicate_key(self):
        spec = self.general_spec()
        d = m.make_mail_draft(self.cfg, spec, self.root)
        import json
        legacy = dict(account=self.cfg['account'], sender=m.sender_address(self.cfg), to=spec['to'],
                      subject=spec['subject'], body=spec['body'], html=spec['html'], assets=d['assets'])
        expected = m.digest(json.dumps(legacy, ensure_ascii=False, sort_keys=True).encode('utf-8'))
        self.assertEqual(d['appkey'], expected)

    def test_reply_header_injection_rejected(self):
        spec = self.general_spec()
        spec['in_reply_to'] = '<a@example.org>\nBcc: x@example.org'
        with self.assertRaises(ValueError): m.make_mail_draft(self.cfg, spec, self.root)

    def test_chinese_pdf_and_single_recipient(self):
        d = self.draft()
        msg = m.parse(d['raw'])
        self.assertIn('科研岗', str(msg['Subject']))
        self.assertIn(self.cfg['profile'], msg.get_body().get_content())
        self.assertEqual(next(msg.iter_attachments()).get_filename(), '中文简历.pdf')
        self.assertEqual(next(msg.iter_attachments()).get_payload(decode=True), self.pdf.read_bytes())

    def test_reject_multiple_recipients_and_header_injection(self):
        for bad in ['a@example.org,b@example.org','a@example.org\nBcc: x@example.org','']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.draft(bad)

    def test_gate_and_atomic_duplicate_claim(self):
        d = self.draft()
        with self.assertRaises(ValueError):
            m.require_enabled(self.db, self.cfg['account'])
        m.save_draft(self.db, d)
        self.assertTrue(m.claim(self.db, d, 0))
        self.assertFalse(m.claim(self.db, d, 0))

    def test_changed_attachment_is_rejected(self):
        d = self.draft()
        self.pdf.write_bytes(b'%PDF-changed')
        with self.assertRaises(ValueError):
            m.check_attachment(d)

    def test_decline_never_opens_smtp(self):
        d = self.draft(self.cfg['account'])
        m.save_draft(self.db, d)
        with patch('builtins.input', return_value='NO'), patch.object(m, 'deliver') as send:
            m.review_send(self.db, self.cfg, d, test=True)
            send.assert_not_called()
        self.assertEqual(self.db.execute('select count(*) from attempts').fetchone()[0], 0)

    def test_timeout_blocks_retry_and_does_not_enable(self):
        d = self.draft(self.cfg['account'])
        m.save_draft(self.db, d)
        with patch('builtins.input', return_value=m.approval(d)), patch.object(m, 'deliver', side_effect=TimeoutError):
            m.review_send(self.db, self.cfg, d, test=True)
        self.assertEqual(self.db.execute('select status from attempts').fetchone()[0], '结果不明')
        self.assertFalse(m.claim(self.db, d, 0))
        with self.assertRaises(ValueError):
            m.require_enabled(self.db, self.cfg['account'])

    def test_accepted_is_submission_not_receipt(self):
        d = self.draft(self.cfg['account'])
        m.save_draft(self.db, d)
        with patch('builtins.input', return_value=m.approval(d)), patch.object(m, 'deliver'):
            m.review_send(self.db, self.cfg, d, test=True)
        self.assertEqual(self.db.execute('select status from attempts').fetchone()[0], '已提交发送')
        with self.assertRaises(ValueError):
            m.require_enabled(self.db, self.cfg['account'])

    def test_csv_and_excel_import_chinese_fields(self):
        row = {'单位':'测试单位','岗位':'科研岗','性质':'高校','联系人':'张老师',
               '邮箱':'hr@example.org','简历路径':str(self.pdf)}
        path = self.root / 'input.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=row)
            writer.writeheader(); writer.writerow(row)
        self.assertEqual(m.rows(path), [row])
        try:
            import openpyxl
        except ImportError:
            self.skipTest('optional openpyxl unavailable')
        wb = openpyxl.Workbook()
        wb.active.append(list(row)); wb.active.append(list(row.values()))
        path = self.root / 'input.xlsx'; wb.save(path); wb.close()
        self.assertEqual(m.rows(path), [row])

    def test_smtp_uses_ssl_full_account_and_one_recipient(self):
        d = self.draft()
        with patch.object(m.wincred, 'get', return_value='dummy-test-only'), patch.object(m.smtplib, 'SMTP_SSL') as ssl_client:
            smtp = ssl_client.return_value
            smtp.send_message.return_value = {}
            m.deliver(self.cfg, d)
            self.assertEqual(ssl_client.call_args.args, ('smtp.qq.com', 465))
            self.assertTrue(ssl_client.call_args.kwargs['context'].check_hostname)
            self.assertEqual(smtp.login.call_args.args[0], self.cfg['account'])
            self.assertEqual(smtp.send_message.call_args.kwargs['to_addrs'], [d['recipient']])

    def test_formal_send_gate_prevents_any_transport(self):
        d = self.draft()
        with patch.object(m, 'deliver') as send, self.assertRaises(ValueError):
            m.review_send(self.db, self.cfg, d)
        send.assert_not_called()


if __name__ == '__main__':
    unittest.main()

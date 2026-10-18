"""Explicitly save a reviewed local draft to QQ Drafts using IMAP APPEND, never SMTP."""
import json
import re
from inbox import Mailbox, parse


class DraftSaveError(Exception):
    def __init__(self, uncertain=False):
        super().__init__('Draft save result requires review' if uncertain else 'Draft save rejected')
        self.uncertain = uncertain


def append_and_verify(box, raw):
    data = raw.encode('ascii')
    if len(data) > 25 * 1024 * 1024: raise ValueError('草稿超过25 MiB保存上限。')
    msg = parse(data)
    mid = str(msg.get('Message-ID', ''))
    if not re.fullmatch(r'<[^<>\s"\r\n]{1,500}>', mid): raise ValueError('草稿缺少有效Message-ID。')
    # Select read-only to verify the known QQ drafts folder exists. Never create folders.
    status, _ = box.client.select('Drafts', readonly=True)
    if status != 'OK': raise DraftSaveError()
    try:
        status, _ = box.client.append('Drafts', r'(\Draft)', None, data)
    except BaseException as exc:
        # The server might have accepted the literal before a disconnect/timeout.
        raise DraftSaveError(uncertain=True) from None
    if status != 'OK': raise DraftSaveError()
    result = dict(folder='Drafts', accepted=True, verified=False, sent=False)
    try:
        status, _ = box.client.select('Drafts', readonly=True)
        if status != 'OK': return result
        status, found = box.client.uid('SEARCH', None, 'HEADER', 'Message-ID', '"' + mid + '"')
        if status != 'OK' or not found or not found[0]: return result
        uid = found[0].split()[-1].decode()
        status, fetched = box.client.uid('FETCH', uid, '(UID FLAGS BODY.PEEK[]<0.' + str(len(data) + 65536) + '>)')
        if status != 'OK': return result
        tuples = [p for p in fetched if isinstance(p, tuple)]
        restored = parse(b''.join(p[1] for p in tuples))
        # Providers may add headers; compare the MIME payload/headers we supplied, not byte-for-byte transport framing.
        leaves = lambda m: [(p.get_content_type(), str(p.get_filename() or ''), str(p.get('Content-ID','')), p.get_payload(decode=True)) for p in m.walk() if not p.is_multipart()]
        verified = (str(restored.get('Message-ID','')) == mid and
                    all(str(restored.get(h,'')) == str(msg.get(h,'')) for h in ('From','To','Subject','In-Reply-To','References')) and
                    leaves(restored) == leaves(msg) and
                    any(b'\\Draft' in p[0] for p in tuples))
        result.update(uid=uid, verified=verified)
    except BaseException:
        pass  # APPEND was accepted: never append again merely because readback failed.
    return result


def save_draft(db, config, draft):
    from mailer import check_attachment, show, sender_address, now
    if draft['account'] != config['account'] or parse(draft['raw'].encode('ascii'))['From'].addresses[0].addr_spec.lower() != sender_address(config):
        raise ValueError('草稿与当前发件身份不匹配，请重新生成。')
    existing = db.execute('SELECT status FROM remote_drafts WHERE account=? AND draft_id=?', (config['account'], draft['id'])).fetchone()
    if existing and existing['status'] in ('已保存', '结果不明', '保存中'):
        print('阻止重复保存：此草稿状态为' + existing['status'] + '，请先在QQ草稿箱核查。未发送。')
        return
    check_attachment(draft)
    show(draft)
    phrase = '保存草稿 ' + draft['id']
    if input('仅保存到QQ邮箱草稿箱，不发信。请输入「' + phrase + '」；其他取消：\n').strip() != phrase:
        print('已取消，未保存、未发送。')
        return
    check_attachment(draft)
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT status FROM remote_drafts WHERE account=? AND draft_id=?', (config['account'], draft['id'])).fetchone()
        if row and row['status'] in ('已保存', '结果不明', '保存中'):
            db.rollback()
            print('另一操作已保存或正在保存，未重复操作。')
            return
        db.execute('INSERT OR REPLACE INTO remote_drafts(account,draft_id,status,date,result) VALUES (?,?,?,?,?)',
                   (config['account'], draft['id'], '保存中', now(), ''))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    status, result = '结果不明', dict(sent=False)
    try:
        with Mailbox(config) as box:
            result = append_and_verify(box, draft['raw'])
        status = '已保存'
    except DraftSaveError as exc:
        status = '结果不明' if exc.uncertain else '保存失败'
        result['error_type'] = 'DraftSaveError'
    except BaseException as exc:
        # An unexpected interruption may land immediately after an accepted APPEND; block retries conservatively.
        result['error_type'] = type(exc).__name__
        if result.get('accepted'): status = '已保存'
    finally:
        db.execute('UPDATE remote_drafts SET status=?,date=?,result=? WHERE account=? AND draft_id=?',
                   (status, now(), json.dumps(result, ensure_ascii=False), config['account'], draft['id']))
        db.commit()
    print(json.dumps(dict(status=status, draft_id=draft['id'], **result), ensure_ascii=False, indent=2))

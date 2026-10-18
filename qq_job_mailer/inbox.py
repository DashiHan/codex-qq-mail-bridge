"""Read-only QQ IMAP access. No mailbox mutation, remote content loading or credential logging."""
import hashlib
import imaplib
import re
import ssl
from datetime import date
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import Path
import wincred

MAX_MESSAGE = 25 * 1024 * 1024
MAX_SCAN = 500
HEADER_FIELDS = 'FROM TO REPLY-TO SUBJECT DATE MESSAGE-ID REFERENCES'


def parse(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'): self.hidden += 1
        if tag in ('p', 'br', 'div', 'li', 'tr', 'h1', 'h2'): self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden: self.hidden -= 1
        if tag in ('p', 'div', 'li', 'tr'): self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def body_text(msg):
    part = msg.get_body(preferencelist=('plain', 'html'))
    if part is None: return ''
    try:
        content = part.get_content(errors='replace')
    except (LookupError, UnicodeError):
        content = part.get_payload(decode=True).decode('utf-8', errors='replace')
    if part.get_content_subtype() == 'html':
        parser = TextHTML()
        parser.feed(content)
        return ''.join(parser.parts).strip()
    return content


def attachment_parts(msg):
    parts = []
    def visit(part):
        if part.get_filename() is not None or part.get_content_disposition() == 'attachment':
            parts.append(part)
        elif part.is_multipart():
            for child in part.iter_parts(): visit(child)
    visit(msg)
    return parts


def attachment_data(part):
    payload = part.get_payload(decode=True)
    if payload is not None: return payload
    if part.get_content_type() == 'message/rfc822':
        nested = part.get_payload()
        if isinstance(nested, list):
            return b'\r\n'.join(child.as_bytes(policy=policy.SMTP) for child in nested)
    return part.as_bytes(policy=policy.SMTP) if part.is_multipart() else b''


def attachment_list(msg):
    return [dict(index=i, filename=str(p.get_filename() or 'attachment.bin'),
                 content_type=p.get_content_type(), inline=p.get_content_disposition() == 'inline',
                 size=len(attachment_data(p)))
            for i, p in enumerate(attachment_parts(msg), 1)]


def message_ids(value):
    return re.findall(r'<[^<>\s\r\n]{1,500}>', str(value or ''))


def reply_spec(msg, body, subject=None):
    candidates = getaddresses([str(msg.get('Reply-To') or msg.get('From') or '')])
    addresses = [addr for _, addr in candidates if addr]
    if len(addresses) != 1:
        raise ValueError('原邮件回复地址不唯一，请人工指定收件地址。')
    original = str(msg.get('Subject', ''))
    title = subject or (original if re.match(r'^re\s*:', original, re.I) else 'Re: ' + original)
    ids = message_ids(msg.get('Message-ID'))
    references = message_ids(msg.get('References'))
    if ids and ids[0] not in references: references.append(ids[0])
    # Quote a bounded portion of the original as plain text, never execute its HTML.
    quote = '\n'.join('> ' + line for line in body_text(msg)[:12000].splitlines())
    return dict(to=addresses[0], subject=title,
                body=body + '\n\n----- 原邮件 / Original message -----\n' + quote,
                in_reply_to=ids[0] if ids else '', references=' '.join(references[-20:]))


def safe_filename(value):
    name = str(value or 'attachment.bin').replace('\\', '/').split('/')[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:160] or 'attachment.bin'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I): name = '_' + name
    return name


class Mailbox:
    def __init__(self, config):
        self.config, self.client, self.validity = config, None, None

    def __enter__(self):
        try:
            self.client = imaplib.IMAP4_SSL('imap.qq.com', 993, ssl_context=ssl.create_default_context(), timeout=20)
            secret = wincred.get(self.config['account'])
            try: self.client.login(self.config['account'], secret)
            finally: secret = None
            capabilities = {x.decode().upper() if isinstance(x, bytes) else x.upper() for x in self.client.capabilities}
            if 'ID' in capabilities:
                imaplib.Commands['ID'] = ('AUTH',)
                self.client._simple_command('ID', '("name" "Codex QQ Mail Bridge" "version" "1.1" "vendor" "personal-tool")')
            status, _ = self.client.select('INBOX', readonly=True)
            if status != 'OK': raise ValueError('无法只读打开收件箱，请检查IMAP服务与设备验证。')
            _, data = self.client.response('UIDVALIDITY')
            if not data or not data[0] or not data[0].isdigit(): raise ValueError('服务器未返回有效邮箱版本。')
            self.validity = data[0].decode()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.client:
            try: self.client.logout()
            except Exception: pass

    def _uid(self, ref):
        if not re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', str(ref)):
            raise ValueError('邮件编号必须为列表返回的 邮箱版本:UID。')
        validity, uid = ref.split(':')
        if validity != self.validity: raise ValueError('邮箱版本已变化，请重新列出邮件。')
        return uid

    def list_messages(self, limit=20, unread=False, sender=None, subject=None, since=None, before=None):
        if not 1 <= limit <= 100: raise ValueError('limit 必须为1到100。')
        criteria = ['UNSEEN' if unread else 'ALL']
        for key, value in (('SINCE', since), ('BEFORE', before)):
            if value:
                try: parsed = date.fromisoformat(value)
                except (ValueError, TypeError): raise ValueError('日期格式必须为YYYY-MM-DD。') from None
                months = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
                criteria.extend([key, '%02d-%s-%04d' % (parsed.day, months[parsed.month-1], parsed.year)])
        status, data = self.client.uid('SEARCH', None, *criteria)
        if status != 'OK': raise ValueError('邮件搜索失败。')
        uids = sorted((x for x in (data[0] or b'').split() if x.isdigit()), key=int, reverse=True)
        total = len(uids)
        selected = uids[:MAX_SCAN if sender or subject else limit]
        records = []
        for start in range(0, len(selected), 50):
            batch = selected[start:start+50]
            status, result = self.client.uid('FETCH', b','.join(batch).decode(),
                '(UID FLAGS BODY.PEEK[HEADER.FIELDS (' + HEADER_FIELDS + ')]<0.65536>)')
            if status != 'OK': raise ValueError('邮件头读取失败。')
            for part in result:
                if not isinstance(part, tuple): continue
                match = re.search(rb'UID ([0-9]+)', part[0], re.I)
                if not match: continue
                msg = parse(part[1])
                row = dict(id=self.validity + ':' + match[1].decode(),
                           sender=str(msg.get('From', '')), subject=str(msg.get('Subject', '')),
                           date=str(msg.get('Date', '')), unread=b'\\Seen' not in imaplib.ParseFlags(part[0]))
                if sender and sender.casefold() not in row['sender'].casefold(): continue
                if subject and subject.casefold() not in row['subject'].casefold(): continue
                records.append(row)
        records.sort(key=lambda r:int(r['id'].split(':')[1]), reverse=True)
        return dict(mailbox='INBOX', readonly=True, candidates=total, scanned=len(selected),
                    search_truncated=(bool(sender or subject) and total > MAX_SCAN),
                    returned=len(records[:limit]), messages=records[:limit])

    def _message(self, ref):
        uid = self._uid(ref)
        status, result = self.client.uid('FETCH', uid, '(RFC822.SIZE)')
        sizes = re.findall(rb'RFC822.SIZE ([0-9]+)', b' '.join(p[0] if isinstance(p, tuple) else p for p in result if p))
        if status != 'OK' or not sizes: raise ValueError('邮件不存在或无法读取大小。')
        if int(sizes[0]) > MAX_MESSAGE: raise ValueError('邮件超过25 MiB读取上限。')
        status, result = self.client.uid('FETCH', uid, '(BODY.PEEK[]<0.' + str(MAX_MESSAGE + 1) + '>)')
        chunks = [p[1] for p in result if isinstance(p, tuple)]
        if status != 'OK' or not chunks: raise ValueError('邮件不存在或正文读取失败。')
        raw = b''.join(chunks)
        if len(raw) > MAX_MESSAGE: raise ValueError('邮件超过25 MiB读取上限。')
        return parse(raw)

    def read_message(self, ref, max_chars=12000):
        if not 1 <= max_chars <= 100000: raise ValueError('max-chars 必须为1到100000。')
        msg = self._message(ref)
        text = body_text(msg)
        return dict(id=ref, sender=str(msg.get('From','')), to=str(msg.get('To','')),
                    reply_to=str(msg.get('Reply-To','')), subject=str(msg.get('Subject','')),
                    date=str(msg.get('Date','')), body=text[:max_chars], body_truncated=len(text)>max_chars,
                    attachments=attachment_list(msg), readonly=True)

    def attachments(self, ref):
        return dict(id=ref, attachments=attachment_list(self._message(ref)), readonly=True)

    def download(self, ref, index, output):
        msg = self._message(ref)
        parts = attachment_parts(msg)
        if not 1 <= index <= len(parts): raise ValueError('附件编号不存在。')
        part = parts[index-1]
        data = attachment_data(part)
        folder = Path(output).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        name = safe_filename(part.get_filename())
        path = folder / name
        for number in range(1000):
            if number: path = folder / (Path(name).stem + '-' + str(number) + Path(name).suffix)
            try:
                with path.open('xb') as stream: stream.write(data)
                return dict(path=str(path), size=len(data), sha256=hashlib.sha256(data).hexdigest(), opened=False)
            except FileExistsError: continue
        raise ValueError('附件文件名冲突过多，请选择其他目录。')

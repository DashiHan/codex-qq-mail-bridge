"""QQ SMTP job mailer: local credentials, immutable drafts, explicit per-mail approval."""
import argparse
import csv
import getpass
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import smtplib
import socket
import sqlite3
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, format_datetime, make_msgid
import wincred

ROOT = Path(__file__).resolve().parent
KINDS = ('高校', '研究所', '企业')
BLOCKED = ('发送中', '结果不明', '已提交发送')


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def address(value):
    value = str(value).strip()
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}', value):
        raise ValueError('邮箱必须是单个完整 ASCII 地址，不得含姓名、逗号、空格或换行。')
    return value.lower()


def sender_address(c):
    sender = address(c.get('sender', c['account']))
    if not sender.endswith(('@qq.com', '@foxmail.com')):
        raise ValueError('发件地址必须是 QQ 或 Foxmail 邮箱。')
    return sender


def config():
    path = ROOT / 'config.json'
    if not path.exists():
        raise ValueError('请先在本地终端运行 setup。')
    c = json.loads(path.read_text(encoding='utf-8'))
    c['account'] = address(c['account'])
    if not c['account'].endswith('@qq.com'):
        raise ValueError('请使用完整的 @qq.com 邮箱地址。')
    c['sender'] = sender_address(c)
    c['interval'] = max(60, int(c.get('interval', 60)))
    return c


def database(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS attempts(
      id INTEGER PRIMARY KEY, draft_id TEXT, appkey TEXT, account TEXT,
      unit TEXT, role TEXT, recipient TEXT, resume TEXT, date TEXT,
      status TEXT, kind TEXT, message_id TEXT, reason TEXT, epoch REAL);
    CREATE TABLE IF NOT EXISTS enabled(account TEXT PRIMARY KEY, confirmed TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS one_submission ON attempts(appkey)
      WHERE status IN ('发送中','结果不明','已提交发送');
    ''')
    return db


def parse(raw):
    return BytesParser(policy=policy.default).parsebytes(raw.encode('utf-8'))


def message(c, recipient, subject, body, pdf=None):
    msg = EmailMessage(policy=policy.SMTP)
    msg['From'] = formataddr((c['name'], sender_address(c)))
    msg['To'] = address(recipient)
    msg['Subject'] = subject
    msg['Date'] = format_datetime(datetime.now(timezone(timedelta(hours=8))))
    msg['Message-ID'] = make_msgid(domain='qq.com')
    msg.set_content(body, charset='utf-8', cte='base64')
    if pdf:
        msg.add_attachment(pdf.read_bytes(), maintype='application', subtype='pdf', filename=pdf.name)
    return msg


def make_draft(c, row, base):
    row = {str(k).strip(): str(v or '').strip() for k, v in row.items() if k is not None}
    for key in ('单位', '岗位', '性质', '邮箱'):
        if not row.get(key):
            raise ValueError('缺少字段：' + key)
    kind = row['性质']
    if kind not in KINDS:
        raise ValueError('性质只能填写高校、研究所或企业。')
    recipient = address(row['邮箱'])
    resume = row.get('简历路径') or c['resumes'].get(kind)
    if not resume:
        raise ValueError('未配置 ' + kind + ' 简历。')
    pdf = Path(resume).expanduser()
    if not pdf.is_absolute():
        pdf = base / pdf
    pdf = pdf.resolve()
    if pdf.suffix.lower() != '.pdf' or not pdf.is_file():
        raise ValueError('简历必须是存在的 PDF 文件：' + str(pdf))
    content = pdf.read_bytes()
    if not content.startswith(b'%PDF-') or len(content) > 15 * 1024 * 1024:
        raise ValueError('简历不是 PDF，或超过本工具15 MiB限制。')
    values = dict(row, 姓名=c['name'], 个人简介=c['profile'], 电话=c['phone'], 发件邮箱=sender_address(c))
    values['称呼'] = row.get('联系人') or '招聘负责人'
    body = (ROOT / 'templates' / (kind + '.txt')).read_text(encoding='utf-8').format_map(values)
    subject = row.get('主题') or f"应聘{row['单位']}{row['岗位']}—{c['name']}"
    msg = message(c, recipient, subject, body, pdf)
    appkey = digest('|'.join([c['account'], row['单位'].casefold(), row['岗位'].casefold(), recipient]).encode())
    return dict(id=secrets.token_hex(6), account=c['account'], unit=row['单位'], role=row['岗位'],
                recipient=recipient, resume=str(pdf), attachment_hash=digest(content), appkey=appkey,
                raw=msg.as_bytes().decode('ascii'), kind='job')


def make_mail_draft(c, spec, base):
    recipient = address(spec['to'])
    subject, body = spec['subject'], spec['body']
    if not isinstance(subject, str) or not subject.strip() or not isinstance(body, str):
        raise ValueError('邮件需要主题和文字正文。')
    msg = message(c, recipient, subject, body)
    for key, header in (('in_reply_to', 'In-Reply-To'), ('references', 'References')):
        value = spec.get(key, '')
        if value:
            if not isinstance(value, str) or not re.fullmatch(r'<[^<>\s\r\n]{1,500}>(?: <[^<>\s\r\n]{1,500}>)*', value):
                raise ValueError('回复邮件的线程标识格式不正确。')
            if key == 'in_reply_to' and ' ' in value:
                raise ValueError('In-Reply-To只能指定一封原邮件。')
            msg[header] = value
    html = spec.get('html')
    if html:
        msg.add_alternative(html, subtype='html', charset='utf-8', cte='base64')
    assets, total, cids = [], 0, set()

    def load_asset(value, inline=False):
        nonlocal total
        path = Path(value).expanduser()
        path = (base / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file() or path.stat().st_size > 15 * 1024 * 1024:
            raise ValueError('附件不存在或超过15 MiB。')
        content = path.read_bytes()
        total += len(content)
        if total > 15 * 1024 * 1024:
            raise ValueError('所有附件合计不得超过15 MiB。')
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        assets.append(dict(path=str(path), hash=digest(content), size=len(content), inline=inline))
        return path, content, mime.split('/', 1)

    for item in spec.get('inline_images', []):
        cid = item['cid']
        if not html or not re.fullmatch(r'[A-Za-z0-9_.@-]+', cid) or cid in cids or ('cid:' + cid) not in html:
            raise ValueError('内嵌图片需要唯一CID及对应HTML引用。')
        cids.add(cid)
        path, content, (maintype, subtype) = load_asset(item['path'], True)
        if maintype != 'image':
            raise ValueError('内嵌文件必须是图片。')
        msg.get_payload()[-1].add_related(content, maintype=maintype, subtype=subtype,
                                        cid='<' + cid + '>', disposition='inline', filename=path.name)
    for value in spec.get('attachments', []):
        path, content, (maintype, subtype) = load_asset(value)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=path.name)
    identity = dict(account=c['account'], sender=sender_address(c), to=recipient,
                    subject=subject, body=body, html=html, assets=assets)
    if spec.get('in_reply_to') or spec.get('references'):
        identity.update(in_reply_to=spec.get('in_reply_to', ''), references=spec.get('references', ''))
    appkey = digest(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    return dict(id=secrets.token_hex(6), account=c['account'], unit='普通邮件', role=subject,
                recipient=recipient, resume='', attachment_hash='', assets=assets,
                appkey=appkey, raw=msg.as_bytes().decode('ascii'), kind='mail')


def save_draft(db, d):
    db.execute('INSERT INTO drafts VALUES (?,?)', (d['id'], json.dumps(d, ensure_ascii=False)))
    db.commit()
    folder = ROOT / 'previews'
    folder.mkdir(exist_ok=True)
    (folder / (d['id'] + '.eml')).write_bytes(d['raw'].encode('ascii'))


def check_attachment(d):
    for asset in d.get('assets', []):
        path = Path(asset['path'])
        if not path.is_file() or digest(path.read_bytes()) != asset['hash']:
            raise ValueError('附件或内嵌图片已变化，请重新生成并审核。')
    if d['resume'] and digest(Path(d['resume']).read_bytes()) != d['attachment_hash']:
        raise ValueError('简历文件已变化，请重新 prepare 并审核。')


def require_enabled(db, account):
    if not db.execute('SELECT 1 FROM enabled WHERE account=?', (account,)).fetchone():
        raise ValueError('正式投递尚未启用：先 test，再在收件箱确认，运行 confirm-test。')


def approval(d):
    return '发送 ' + d['id'] + ' ' + d['recipient']


def show(d):
    msg = parse(d['raw'])
    print('\n' + '=' * 64)
    print('草稿编号：', d['id'], '\n发件人：', msg['From'], '\n收件人：', msg['To'])
    print('单位：', d['unit'], '\n岗位：', d['role'], '\n主题：', msg['Subject'])
    print('\n正文：\n' + msg.get_body(preferencelist=('plain',)).get_content().replace('\r\n','\n'))
    if d.get('kind') != 'mail':
        print('附件：', d['resume'] or '无')
    if d['resume']:
        print('附件 SHA256：', d['attachment_hash'])
        print('附件大小：', len(next(msg.iter_attachments()).get_payload(decode=True)), '字节')
    if d.get('kind') == 'mail':
        if msg.get_body(preferencelist=('html',)):
            print('HTML正文：', msg.get_body(preferencelist=('html',)).get_content())
        for asset in d.get('assets', []):
            print('正文图片：' if asset['inline'] else '普通附件：', asset['path'], '\n大小：', asset['size'], '字节；SHA256：', asset['hash'])
    if msg.get('In-Reply-To'): print('回复原邮件：', msg['In-Reply-To'])
    print('Message-ID：', msg['Message-ID'])


def claim(db, d, interval):
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM attempts WHERE appkey=? AND status IN ('发送中','结果不明','已提交发送')", (d['appkey'],)).fetchone():
            db.rollback()
            return False
        last = db.execute('SELECT MAX(epoch) FROM attempts WHERE account=?', (d['account'],)).fetchone()[0]
        if last and time.time() - last < interval:
            raise ValueError('发送间隔不足，请稍后再运行（至少60秒）。')
        db.execute('''INSERT INTO attempts(draft_id,appkey,account,unit,role,recipient,resume,date,status,kind,message_id,reason,epoch)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (d['id'], d['appkey'], d['account'], d['unit'], d['role'],
            d['recipient'], d['resume'], now(), '发送中', d['kind'], str(parse(d['raw'])['Message-ID']), '', time.time()))
        db.commit()
        return True
    except BaseException:
        db.rollback()
        raise


def deliver(c, d):
    # No SMTP debuglevel. No exception/server response text is printed or logged.
    secret = wincred.get(c['account'])
    smtp = None
    try:
        smtp = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30, context=ssl.create_default_context())
        smtp.login(c['account'], secret)
        refused = smtp.send_message(parse(d['raw']), from_addr=sender_address(c), to_addrs=[d['recipient']])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    finally:
        secret = None
        # close avoids a QUIT failure masking a successful DATA acceptance.
        if smtp:
            smtp.close()


def review_send(db, c, d, test=False):
    if d['account'] != c['account']:
        raise ValueError('草稿与当前发件邮箱不匹配。')
    if parse(d['raw'])['From'].addresses[0].addr_spec.lower() != sender_address(c):
        raise ValueError('草稿发件地址已变化，请重新生成并审核。')
    if test:
        if d['recipient'] != c['account']:
            raise ValueError('测试只允许发给自己。')
    else:
        require_enabled(db, c['account'])
        if d['kind'] not in ('job', 'mail'):
            raise ValueError('请使用 test 发送测试邮件。')
    check_attachment(d)
    show(d)
    print('\n请核对招聘公告中的邮箱、岗位、称呼和附件；.eml 可本地打开预览附件。')
    if input('仅发送本封，请完整输入「' + approval(d) + '」；其他输入取消：\n').strip() != approval(d):
        print('已取消，未发送。')
        return
    check_attachment(d)
    if not claim(db, d, c.get('interval', 60)):
        raise ValueError('已存在发送中、结果不明或已提交记录，阻止重复发送。')
    status, reason = '结果不明', ''
    interrupted = False
    try:
        deliver(c, d)
        status = '已提交发送'
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
        status, reason = '发送失败', type(exc).__name__
    except BaseException as exc:
        # Timeout/disconnect/crash: do NOT auto-retry. Server may have accepted DATA.
        reason = type(exc).__name__
        interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
    finally:
        db.execute('UPDATE attempts SET status=?,reason=? WHERE draft_id=? AND status=?',
                   (status, reason, d['id'], '发送中'))
        db.commit()
    print(status + ('（服务器已接受；不代表收件人已收到或阅读）' if status == '已提交发送' else '；未自动重试。错误类别：' + reason))
    if interrupted:
        raise KeyboardInterrupt


def rows(path):
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    if path.suffix.lower() == '.xlsx':
        try:
            import openpyxl
        except ImportError:
            raise ValueError('读取.xlsx需要 openpyxl；或用Excel另存为 CSV UTF-8（零依赖）。') from None
        wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
        try:
            table = list(wb.active.values)
            if not table:
                return []
            if any(isinstance(v, str) and v.startswith('=') for row in table for v in row):
                raise ValueError('输入表不允许公式，请粘贴为值。')
            return [dict(zip(table[0], row)) for row in table[1:] if any(row)]
        finally:
            wb.close()
    raise ValueError('仅支持 .csv 或 .xlsx。')


def setup(db):
    if not sys.stdin.isatty():
        raise ValueError('setup 必须在本机交互终端运行，不能通过聊天或管道输入授权码。')
    account = address(input('完整 QQ 邮箱地址：').strip())
    if not account.endswith('@qq.com'):
        raise ValueError('请使用 @qq.com 完整地址。')
    name = input('署名姓名：').strip()
    if not name or '\n' in name or '\r' in name:
        raise ValueError('姓名不能为空或含换行。')
    phone = input('联系电话（可留空）：').strip()
    profile = input('个人简介（请填写真实情况）：').strip()
    if not profile:
        raise ValueError('请填写真实、完整的个人简介。')
    resumes = {}
    for kind in KINDS:
        value = input(kind + ' PDF简历绝对路径（可暂留空）：').strip().strip('"')
        if value:
            p = Path(value).expanduser().resolve()
            if p.suffix.lower() != '.pdf' or not p.is_file():
                raise ValueError('PDF路径不存在：' + str(p))
            resumes[kind] = str(p)
    # getpass must never fall back to visible stdin.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        secret = getpass.getpass('QQ 邮箱授权码（隐藏输入；不是QQ密码）：')
    if not re.fullmatch(r'[A-Za-z]{16}', secret.strip()):
        raise ValueError('授权码应为16位英文字母，请核对。')
    try:
        wincred.put(account, secret.strip())
    finally:
        secret = None
    c = dict(account=account, name=name, phone=phone, profile=profile, resumes=resumes, interval=60,
             configured_epoch=time.time())
    (ROOT / 'config.json').write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')
    db.execute('DELETE FROM enabled WHERE account=?', (account,))
    db.commit()
    print('已保存非敏感配置与 Windows 安全凭据。正式投递仍锁定，请运行 test。')


def export(db):
    path = ROOT / '投递记录.csv'
    records = db.execute('SELECT id,unit,role,recipient,date,resume,status,kind,message_id,reason FROM attempts ORDER BY id').fetchall()
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['记录号','单位','岗位','邮箱','投递日期','所用简历','发送状态','类型','Message-ID','错误类别'])
        for r in records:
            writer.writerow([("'" + str(v)) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in r])
    print('记录已导出：', path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    for cmd in ('setup','test','confirm-test','doctor','records','forget'):
        sub.add_parser(cmd)
    for name in ('inbox', 'search'):
        q = sub.add_parser(name)
        q.add_argument('--limit', type=int, default=20)
        q.add_argument('--unread', action='store_true')
        q.add_argument('--from', dest='sender')
        q.add_argument('--subject')
        q.add_argument('--since')
        q.add_argument('--before')
    for name in ('read', 'attachments', 'download', 'reply'):
        q = sub.add_parser(name)
        q.add_argument('reference')
        if name == 'read': q.add_argument('--max-chars', type=int, default=12000)
        if name == 'download':
            q.add_argument('index', type=int)
            q.add_argument('--output', type=Path, required=True)
        if name == 'reply':
            q.add_argument('--body-file', type=Path, required=True)
            q.add_argument('--subject')
    compose = sub.add_parser('prepare-mail'); compose.add_argument('spec', type=Path)
    prep = sub.add_parser('prepare'); prep.add_argument('table', type=Path)
    for cmd in ('preview','send'):
        q = sub.add_parser(cmd); q.add_argument('id')
    resolve = sub.add_parser('resolve'); resolve.add_argument('record', type=int)
    args = p.parse_args()
    if args.cmd == 'doctor':
        print('Python:', sys.version.split()[0], '\n解释器:', sys.executable)
        try:
            import openpyxl
            print('Excel .xlsx: 可用', openpyxl.__version__)
        except ImportError:
            print('Excel .xlsx: 未安装openpyxl；CSV可直接使用。')
        with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=10, context=ssl.create_default_context()) as smtp:
            code, _ = smtp.noop()
            print('SMTP SSL证书验证与连接:', code, '（未登录、未发信）')
        return
    if args.cmd in ('inbox', 'search', 'read', 'attachments', 'download', 'reply'):
        from inbox import Mailbox, reply_spec
        c = config()
        with Mailbox(c) as box:
            if args.cmd in ('inbox', 'search'):
                result = box.list_messages(args.limit, args.unread, args.sender, args.subject, args.since, args.before)
            elif args.cmd == 'read': result = box.read_message(args.reference, args.max_chars)
            elif args.cmd == 'attachments': result = box.attachments(args.reference)
            elif args.cmd == 'download': result = box.download(args.reference, args.index, args.output)
            else:
                spec = reply_spec(box._message(args.reference), args.body_file.read_text(encoding='utf-8-sig'), args.subject)
                d = make_mail_draft(c, spec, args.body_file.resolve().parent)
                with database(ROOT / 'delivery.sqlite3') as db: save_draft(db, d)
                show(d)
                print('仅生成回复草稿，未发送。发送命令：run.ps1 send ' + d['id'])
                return
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    with database(ROOT / 'delivery.sqlite3') as db:
        if args.cmd == 'setup':
            setup(db); return
        if args.cmd == 'records':
            export(db); return
        c = config()
        if args.cmd == 'forget':
            wincred.delete(c['account'])
            db.execute('DELETE FROM enabled WHERE account=?', (c['account'],))
            print('已删除此邮箱的本工具授权码凭据并关闭正式投递。'); return
        if args.cmd == 'prepare-mail':
            path = args.spec.resolve()
            spec = json.loads(path.read_text(encoding='utf-8-sig'))
            d = make_mail_draft(c, spec, path.parent)
            save_draft(db, d)
            show(d)
            print('仅生成草稿；发送命令：run.ps1 send ' + d['id'])
            return
        if args.cmd == 'prepare':
            path = args.table.resolve()
            # Validate whole table before persisting any draft.
            drafts = [make_draft(c, row, path.parent) for row in rows(path)]
            for d in drafts:
                save_draft(db, d)
                show(d)
                print('仅生成草稿；发送命令：.\\run.ps1 send ' + d['id'])
            print('共生成', len(drafts), '封；未发送。'); return
        if args.cmd == 'test':
            resume = next((c['resumes'][k] for k in KINDS if c['resumes'].get(k)), '')
            pdf = Path(resume) if resume else None
            if pdf and (not pdf.is_file() or pdf.suffix.lower() != '.pdf' or not pdf.read_bytes().startswith(b'%PDF-') or pdf.stat().st_size > 15*1024*1024):
                raise ValueError('测试附件必须是有效PDF路径，且不超过15 MiB。')
            msg = message(c, c['account'], 'QQ求职邮件工具—自发测试', '这是一封中文SMTP测试邮件。\n仅用于验证发信及收件。\n如有附件，请核对PDF是否可正常打开。\n请在收件箱核对发件地址、主题和正文后，回到终端运行 confirm-test。', pdf)
            d = dict(id=secrets.token_hex(6), account=c['account'], unit='本机自发测试', role='测试',
                     recipient=c['account'], resume=str(pdf) if pdf else '', attachment_hash=digest(pdf.read_bytes()) if pdf else '', appkey=secrets.token_hex(32), raw=msg.as_bytes().decode('ascii'), kind='test')
            save_draft(db, d); review_send(db, c, d, test=True); return
        if args.cmd == 'confirm-test':
            accepted = db.execute("SELECT id,date FROM attempts WHERE account=? AND kind='test' AND status='已提交发送' AND epoch>? ORDER BY id DESC LIMIT 1", (c['account'], c.get('configured_epoch', 0))).fetchone()
            if not accepted:
                raise ValueError('尚无服务器接受的自发测试记录。')
            print('最新已提交测试：记录', accepted['id'], accepted['date'])
            if input('仅在收件箱实际找到这封测试后输入「已收到测试 ' + c['account'] + '」：\n').strip() == '已收到测试 ' + c['account']:
                db.execute('INSERT OR REPLACE INTO enabled VALUES (?,?)', (c['account'], now()))
                print('已启用正式投递，每封仍需单独审核确认。')
            return
        if args.cmd == 'resolve':
            r = db.execute('SELECT * FROM attempts WHERE id=? AND account=?', (args.record,c['account'])).fetchone()
            if not r or r['status'] not in ('结果不明','发送中'):
                raise ValueError('只能人工处理发送中或结果不明的记录。')
            print(dict(r))
            print('请先核查邮箱发送记录/退信/收件人反馈。没有发送记录不能保证未发送。')
            choice = input('确认已提交请输入「标记已提交」；承担重复风险并允许重试请输入「确认未发送并解锁」；其他取消：')
            state = {'标记已提交':'已提交发送', '确认未发送并解锁':'人工解锁'}.get(choice)
            if state:
                db.execute('UPDATE attempts SET status=?,reason=? WHERE id=?', (state,'用户人工核查',r['id']))
            return
        row = db.execute('SELECT payload FROM drafts WHERE id=?', (args.id,)).fetchone()
        if not row:
            raise ValueError('草稿编号不存在。')
        d = json.loads(row[0])
        if args.cmd == 'preview':
            show(d)
        else:
            review_send(db, c, d)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已中断；请查 records，结果不明不得盲目重试。')
        sys.exit(130)
    except Exception as exc:
        # Only controlled local validation errors are printable; never raw SMTP exceptions.
        if type(exc) is ValueError:
            print('未完成：', str(exc))
        else:
            print('未完成，错误类别：', type(exc).__name__, '（未打印服务器响应或凭据）')
        sys.exit(1)

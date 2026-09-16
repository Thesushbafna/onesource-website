#!/usr/bin/env python3
"""Local-first One Source OS server. Python 3.10+; no third-party dependencies."""
from __future__ import annotations
import argparse, base64, csv, hashlib, io, json, logging, os, secrets, sqlite3, sys, threading, time, urllib.parse, webbrowser
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import core

ROOT=Path(__file__).resolve().parent
MAX_BODY=8*1024*1024
LOG=logging.getLogger('onesource')
RATE_LOCK=threading.Lock(); LOGIN_ATTEMPTS={}

class Handler(BaseHTTPRequestHandler):
    server_version='OneSourceOS'
    def log_message(self,fmt,*args): LOG.info('%s %s',self.client_address[0],fmt%args)
    def db(self): return core.connect(self.server.db_path)
    def security_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")
    def reply(self,status,data,ctype='application/json; charset=utf-8',extra=None):
        raw=json.dumps(data,ensure_ascii=False).encode() if not isinstance(data,bytes) else data
        self.send_response(status); self.security_headers(); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(raw)))
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)
    def valid_host(self):
        host=self.headers.get('Host','').lower()
        if host not in self.server.allowed_hosts:
            self.reply(403,{'error':'Untrusted Host header.'}); return False
        origin=self.headers.get('Origin')
        if origin and urllib.parse.urlparse(origin).netloc.lower()!=host:
            self.reply(403,{'error':'Cross-origin requests are not allowed.'}); return False
        return True
    def read_json(self):
        length=int(self.headers.get('Content-Length','0'))
        core.need(0<length<=MAX_BODY,'Request is empty or too large.')
        core.need(self.headers.get('Content-Type','').split(';')[0]=='application/json','JSON content type required.')
        p=json.loads(self.rfile.read(length)); core.need(isinstance(p,dict),'Expected a JSON object.'); return p
    def auth(self,c,csrf=False):
        token=''
        try:
            jar=cookies.SimpleCookie(); jar.load(self.headers.get('Cookie','')); token=jar['os_session'].value if 'os_session' in jar else ''
        except cookies.CookieError: pass
        u=core.row(c,'SELECT u.*,s.csrf,s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),core.now()))
        if not u: self.reply(401,{'error':'Sign in to continue.'}); return None
        if csrf and not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),u['csrf']): self.reply(403,{'error':'Invalid session security token. Reload and try again.'}); return None
        return u
    def cookie(self,token='',expire=False):
        return 'os_session='+token+'; HttpOnly; SameSite=Strict; Path=/; '+('Max-Age=0' if expire else 'Max-Age=28800')+('; Secure' if self.server.secure_cookie else '')
    def do_GET(self):
        if not self.valid_host(): return
        parsed=urllib.parse.urlparse(self.path); path=parsed.path
        if path=='/health': self.reply(200,{'status':'ok'}); return
        if path in ('/','/index.html','/style.css','/app.js'):
            filename={'/':'index.html','/index.html':'index.html','/style.css':'style.css','/app.js':'app.js'}[path]
            ctype='text/html; charset=utf-8' if filename.endswith('html') else 'text/css; charset=utf-8' if filename.endswith('css') else 'text/javascript; charset=utf-8'
            self.reply(200,(ROOT/'static'/filename).read_bytes(),ctype); return
        c=self.db()
        try:
            user=self.auth(c)
            if not user: return
            if path=='/api/session': self.reply(200,{'user':{k:user[k] for k in ('id','name','username','role')},'csrf':user['csrf']}); return
            if path=='/api/state':
                c.execute('BEGIN'); data=core.snapshot(c,user); c.commit(); self.reply(200,data); return
            if path=='/api/backup':
                core.allowed(user,()); target=sqlite3.connect(':memory:'); c.backup(target)
                if hasattr(target,'serialize'): payload=target.serialize()
                else:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.sqlite3',delete=False) as tmp: temp=tmp.name
                    try:
                        disk=sqlite3.connect(temp); target.backup(disk); disk.close(); payload=Path(temp).read_bytes()
                    finally: Path(temp).unlink(missing_ok=True)
                target.close()
                self.reply(200,payload,'application/octet-stream',{'Content-Disposition':'attachment; filename="onesource-backup-'+core.today()+'.sqlite3"'}); return
            if path=='/api/export':
                q=urllib.parse.parse_qs(parsed.query); dataset=q.get('dataset',['documents'])[0]
                allowed={'parties','items','projects','leads','documents','document_lines','receipts','dispatches','payments','site_logs','changes','clearances','tasks','stock_moves','journal_lines','journals','audit','measurements','credit_instruments'}
                core.need(dataset in allowed,'Unknown export dataset.')
                data=core.rows(c,f'SELECT * FROM {dataset} ORDER BY id')
                out=io.StringIO(); fields=list(data[0]) if data else [r[1] for r in c.execute(f'PRAGMA table_info({dataset})')]
                money_fields={'items':{'sell_rate','buy_rate'},'projects':{'budget'},'leads':{'value'},'documents':{'base','cgst','sgst','igst','total'},'document_lines':{'rate','base','cgst','sgst','igst','total'},'payments':{'cash','tds','retention','advance_used'},'site_logs':{'daily_rate'},'changes':{'value'},'stock_moves':{'value'},'journal_lines':{'debit','credit'},'measurements':{'rate','value'},'credit_instruments':{'face_value','claim_value','accepted_value'}}.get(dataset,set())
                names={k:k+'_inr' if k in money_fields else k.replace('_milli','_quantity') if k.endswith('_milli') else 'gst_percent' if k=='gst_bps' else k for k in fields}
                writer=csv.DictWriter(out,fieldnames=[names[k] for k in fields]); writer.writeheader()
                def safe(v): return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
                for r in data:
                    values={}
                    for k,v in r.items():
                        if k in money_fields and v is not None: values[names[k]]=format(Decimal(v)/100,'.2f')
                        elif k.endswith('_milli') and v is not None: values[names[k]]=format(Decimal(v)/1000,'.3f')
                        elif k=='gst_bps' and v is not None: values[names[k]]=format(Decimal(v)/100,'.2f')
                        else: values[names[k]]=safe(v)
                    writer.writerow(values)
                self.reply(200,('\ufeff'+out.getvalue()).encode(),'text/csv; charset=utf-8',{'Content-Disposition':f'attachment; filename="onesource-{dataset}.csv"'}); return
            if path.startswith('/api/attachment/'):
                aid=int(path.rsplit('/',1)[-1]); obj=core.row(c,'SELECT * FROM attachments WHERE id=?',(aid,)); core.need(obj,'Attachment not found.')
                filename=urllib.parse.quote(obj['filename'],safe='')
                self.reply(200,obj['data'],'application/octet-stream',{'Content-Disposition':"attachment; filename*=UTF-8''"+filename}); return
            self.reply(404,{'error':'Not found.'})
        except core.RuleError as e: self.reply(400,{'error':str(e)})
        except Exception:
            LOG.exception('GET failure'); self.reply(500,{'error':'Server error. Check the terminal log.'})
        finally: c.close()
    def do_POST(self):
        if not self.valid_host(): return
        c=self.db()
        try:
            p=self.read_json(); path=urllib.parse.urlparse(self.path).path
            if path=='/api/login':
                ip=self.client_address[0]
                with RATE_LOCK:
                    attempts=[x for x in LOGIN_ATTEMPTS.get(ip,[]) if time.time()-x<900]
                    LOGIN_ATTEMPTS[ip]=attempts
                    if len(attempts)>=10: self.reply(429,{'error':'Too many attempts. Try again in 15 minutes.'}); return
                u=core.row(c,'SELECT * FROM users WHERE username=? AND active=1',(str(p.get('username','')).strip().lower(),))
                if not u or not core.password_ok(str(p.get('password','')),u['password']):
                    with RATE_LOCK: LOGIN_ATTEMPTS[ip].append(time.time())
                    self.reply(401,{'error':'Incorrect username or password.'}); return
                token=secrets.token_urlsafe(40); csrf=secrets.token_urlsafe(28); expiry=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat(timespec='seconds')
                c.execute('DELETE FROM sessions WHERE expires<?',(core.now(),)); c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,expiry))
                with RATE_LOCK: LOGIN_ATTEMPTS.pop(ip,None)
                self.reply(200,{'csrf':csrf,'user':{k:u[k] for k in ('id','name','username','role')}},extra={'Set-Cookie':self.cookie(token)}); return
            user=self.auth(c,True)
            if not user: return
            if path=='/api/logout':
                c.execute('DELETE FROM sessions WHERE user_id=? AND csrf=?',(user['id'],user['csrf'])); self.reply(200,{'ok':True},extra={'Set-Cookie':self.cookie(expire=True)}); return
            if path=='/api/command':
                rid=self.headers.get('X-Request-ID',''); core.need(8<=len(rid)<=100,'A unique request ID is required.')
                c.execute('BEGIN IMMEDIATE')
                previous=core.row(c,'SELECT * FROM requests WHERE id=?',(rid,))
                if previous:
                    core.need(previous['user_id']==user['id'],'Request ID belongs to another user.'); c.commit(); self.reply(200,json.loads(previous['response'])); return
                result=core.command(c,user,p)
                c.execute('INSERT INTO requests VALUES (?,?,?)',(rid,user['id'],json.dumps(result))); c.commit(); self.reply(200,result); return
            if path=='/api/upload':
                core.allowed(user,('sales','operations','accounts')); entity=p.get('entity'); core.need(entity in ('documents','projects','dispatches','receipts','clearances','changes'),'Invalid attachment record type.')
                obj=core.get(c,entity,p['record_id']); filename=Path(str(p.get('filename','file')).replace('\\','/')).name[:180]
                core.need(Path(filename).suffix.lower() in ('.pdf','.png','.jpg','.jpeg','.webp','.xlsx','.docx','.txt'),'Supported attachments: PDF, images, XLSX, DOCX and TXT.')
                data=base64.b64decode(p.get('data',''),validate=True); core.need(0<len(data)<=5*1024*1024,'Attachment must be between 1 byte and 5 MB.')
                c.execute('BEGIN IMMEDIATE'); aid=core.insert(c,'attachments',dict(entity=entity,record_id=obj['id'],filename=filename,data=data,uploaded_by=user['id'],timestamp=core.now()))
                core.audit(c,user,'attachments',aid,'upload',{'filename':filename,'entity':entity,'record_id':obj['id']}); c.commit(); self.reply(200,{'id':aid,'message':'Attachment saved.'}); return
            self.reply(404,{'error':'Not found.'})
        except (core.RuleError,ValueError,TypeError,KeyError,json.JSONDecodeError) as e:
            if c.in_transaction: c.rollback()
            self.reply(400,{'error':str(e) if isinstance(e,core.RuleError) else 'Invalid or missing input. Check the form and try again.'})
        except sqlite3.IntegrityError:
            if c.in_transaction: c.rollback()
            self.reply(409,{'error':'A duplicate or invalid linked record was detected. Check unique codes, supplier references and team/date entries.'})
        except Exception:
            if c.in_transaction: c.rollback()
            LOG.exception('POST failure'); self.reply(500,{'error':'The transaction was rolled back. Check the terminal log.'})
        finally: c.close()

def main():
    parser=argparse.ArgumentParser(description='One Source CRM + Accounting starter')
    parser.add_argument('--db',default=str(ROOT/'data'/'onesource.sqlite3')); parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--demo',action='store_true',help='Seed fictional data, only when no parties exist.')
    parser.add_argument('--open',action='store_true',help='Open the browser.')
    parser.add_argument('--reset-admin-password',action='store_true',help='Local recovery: rotate admin password and invalidate sessions.')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    password=core.initialize(args.db); c=core.connect(args.db)
    if args.reset_admin_password:
        password=secrets.token_urlsafe(15); c.execute('UPDATE users SET password=? WHERE username=?',(core.password_hash(password),'admin')); c.execute('DELETE FROM sessions')
    if args.demo:
        from seed import seed_demo
        try: c.execute('BEGIN IMMEDIATE'); seed_demo(c); c.commit()
        except Exception: c.rollback(); raise
    c.close()
    host_display='127.0.0.1' if args.host=='0.0.0.0' else args.host
    url=f'http://{host_display}:{args.port}'
    print('\n'+'='*64+'\n ONE SOURCE OS | CRM + OPERATIONS + ACCOUNTING\n'+'='*64,flush=True)
    print(f' Browser: {url}\n Database: {Path(args.db).resolve()}',flush=True)
    if password: print(f'\n FIRST-USE LOGIN\n Username: admin\n Password: {password}\n\n Save this password. It is shown only when created or reset.',flush=True)
    else: print(f'\n Use your existing login.\n Recovery: python app.py --db "{args.db}" --reset-admin-password',flush=True)
    print('\n DEMO / PILOT BUILD. Not a certified statutory accounting system.\n Keep this terminal open. Press Ctrl+C to stop.\n',flush=True)
    server=ThreadingHTTPServer((args.host,args.port),Handler); server.db_path=args.db
    server.secure_cookie=os.getenv('OS_SECURE_COOKIE','0')=='1'
    server.allowed_hosts={f'localhost:{args.port}',f'127.0.0.1:{args.port}',f'{args.host}:{args.port}'}|{x.strip().lower() for x in os.getenv('OS_ALLOWED_HOSTS','').split(',') if x.strip()}
    if args.open: threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nStopped. Your data is saved.')
    finally: server.server_close()
if __name__=='__main__': main()

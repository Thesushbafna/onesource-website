"""One Source OS: transaction-safe business and accounting core (stdlib only)."""
from __future__ import annotations
import sqlite3, json, hashlib, secrets, hmac
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROLES = ('admin', 'sales', 'operations', 'accounts', 'viewer')
DOC_TYPES = ('quote', 'sales_order', 'purchase_order', 'invoice', 'bill')
PREFIX = {'quote':'QT','sales_order':'SO','purchase_order':'PO','invoice':'SI','bill':'PB'}
ACCOUNTS = [
('1000','Bank / cash','Asset'),('1100','Trade receivables','Asset'),
('1110','Retention receivable','Asset'),('1120','TDS receivable','Asset'),
('1200','Inventory','Asset'),('1210','Input CGST','Asset'),('1220','Input SGST','Asset'),
('1230','Input IGST','Asset'),('1300','Supplier advances','Asset'),
('2000','Trade payables','Liability'),('2010','Goods received, not billed','Liability'),
('2020','Retention payable','Liability'),('2030','TDS payable','Liability'),
('2040','Labour accrued','Liability'),('2100','Customer advances','Liability'),
('2210','Output CGST','Liability'),('2220','Output SGST','Liability'),('2230','Output IGST','Liability'),
('3000','Capital / opening balances','Equity'),('4000','Material sales','Revenue'),
('4100','Installation / service revenue','Revenue'),('5000','Material cost dispatched','Expense'),
('5100','Subcontract / direct services','Expense'),('5200','Labour cost','Expense'),
('5300','Freight / site expenses','Expense'),('5400','Office / other expenses','Expense')]

class RuleError(Exception):
    pass

def need(condition, message):
    if not condition: raise RuleError(message)

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def today(): return date.today().isoformat()
def text(value, limit=500): return str(value or '').strip()[:limit]
def num(value, scale=100):
    try:
        x = Decimal(str(value or 0))
        need(x.is_finite() and abs(x) < Decimal('1000000000000'), 'Invalid number or amount too large.')
        return int((x * scale).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError): raise RuleError('Enter a valid number.')
def money(v): return num(v,100)
def quantity(v): return num(v,1000)
def rounded(n, d=1000): return int((Decimal(n)/Decimal(d)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def valid_date(v):
    try: return date.fromisoformat(str(v)).isoformat()
    except (ValueError,TypeError): raise RuleError('Use a valid date (YYYY-MM-DD).')
def password_hash(p):
    salt=secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),310000).hex()
def password_ok(p, stored):
    salt, target=stored.split(':')
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),310000).hex(),target)

def connect(path):
    c=sqlite3.connect(str(path), timeout=20, isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=20000')
    return c

def row(c, sql, args=()):
    r=c.execute(sql,args).fetchone()
    return dict(r) if r else None

def rows(c,sql,args=()): return [dict(r) for r in c.execute(sql,args)]
def get(c,table,id):
    allowed={'parties','items','projects','documents','document_lines','warehouses','receipts','dispatches','payments','journals','site_logs','clearances','changes','tasks','leads','users','measurements','credit_instruments'}
    need(table in allowed,'Invalid record type.')
    r=row(c,f'SELECT * FROM {table} WHERE id=?',(int(id),))
    need(r is not None,'Record not found.')
    return r

def insert(c, table, values):
    cols=list(values)
    q=f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
    return c.execute(q,tuple(values[k] for k in cols)).lastrowid

def settings(c): return {r['key']:json.loads(r['value']) for r in rows(c,'SELECT * FROM settings')}
def set_setting(c,k,v): c.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,json.dumps(v)))

def audit(c,user,entity,record_id,action,detail):
    insert(c,'audit',dict(timestamp=now(),user_id=user['id'],entity=entity,record_id=record_id,action=action,detail=json.dumps(detail,ensure_ascii=False)))

def allowed(user,roles): need(user['role']=='admin' or user['role'] in roles,'Your role cannot perform this action.')

def next_no(c,prefix,dt=None):
    d=date.fromisoformat(dt or today()); fy=d.year if d.month>=4 else d.year-1
    key=f'{prefix}{str(fy)[2:]}{str(fy+1)[2:]}'
    c.execute('INSERT INTO sequences VALUES (?,1) ON CONFLICT(key) DO UPDATE SET value=value+1',(key,))
    n=c.execute('SELECT value FROM sequences WHERE key=?',(key,)).fetchone()[0]
    return f'{key}-{n:05d}'

def check_period(c,dt):
    dt=valid_date(dt)
    locked=settings(c).get('locked_through','')
    need(not locked or dt>locked,'This accounting period is locked. Use an open-period date.')
    need(dt<=today(),'Financial posting dates cannot be in the future.')
    return dt

def initialize(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    c=connect(path); c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sequences(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,name TEXT NOT NULL,role TEXT NOT NULL,password TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),csrf TEXT NOT NULL,expires TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,user_id INTEGER,response TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS parties(id INTEGER PRIMARY KEY,name TEXT NOT NULL,type TEXT NOT NULL,email TEXT DEFAULT '',phone TEXT DEFAULT '',gstin TEXT DEFAULT '',state TEXT DEFAULT '29',address TEXT DEFAULT '',credit_days INTEGER DEFAULT 30,notes TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS warehouses(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,city TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,sku TEXT NOT NULL UNIQUE,name TEXT NOT NULL,category TEXT DEFAULT '',kind TEXT NOT NULL,uom TEXT NOT NULL,hsn TEXT DEFAULT '',sell_rate INTEGER NOT NULL,buy_rate INTEGER NOT NULL,gst_bps INTEGER NOT NULL,reorder_milli INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,client_id INTEGER REFERENCES parties(id),city TEXT,scope TEXT,budget INTEGER NOT NULL DEFAULT 0,area_milli INTEGER DEFAULT 0,start_date TEXT,target_date TEXT,status TEXT,owner TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY,company TEXT NOT NULL,contact TEXT,phone TEXT,scope TEXT,value INTEGER NOT NULL,stage TEXT NOT NULL,probability INTEGER DEFAULT 20,owner TEXT,next_date TEXT,notes TEXT,party_id INTEGER REFERENCES parties(id),quote_id INTEGER);
    CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,number TEXT NOT NULL UNIQUE,type TEXT NOT NULL,party_id INTEGER NOT NULL REFERENCES parties(id),project_id INTEGER REFERENCES projects(id),source_id INTEGER REFERENCES documents(id),receipt_id INTEGER,date TEXT NOT NULL,due_date TEXT NOT NULL,reference TEXT DEFAULT '',status TEXT NOT NULL,tax_mode TEXT NOT NULL,place_of_supply TEXT DEFAULT '',notes TEXT DEFAULT '',base INTEGER NOT NULL,cgst INTEGER NOT NULL,sgst INTEGER NOT NULL,igst INTEGER NOT NULL,total INTEGER NOT NULL,created_by INTEGER REFERENCES users(id),approved_by INTEGER REFERENCES users(id),journal_id INTEGER,reversal_id INTEGER);
    CREATE TABLE IF NOT EXISTS document_lines(id INTEGER PRIMARY KEY,document_id INTEGER NOT NULL REFERENCES documents(id),source_line_id INTEGER REFERENCES document_lines(id),item_id INTEGER NOT NULL REFERENCES items(id),description TEXT NOT NULL,qty_milli INTEGER NOT NULL CHECK(qty_milli>0),rate INTEGER NOT NULL CHECK(rate>=0),gst_bps INTEGER NOT NULL CHECK(gst_bps>=0),base INTEGER NOT NULL,cgst INTEGER NOT NULL,sgst INTEGER NOT NULL,igst INTEGER NOT NULL,total INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS journals(id INTEGER PRIMARY KEY,number TEXT UNIQUE NOT NULL,date TEXT NOT NULL,memo TEXT NOT NULL,source TEXT NOT NULL,source_id INTEGER,created_by INTEGER REFERENCES users(id),reverses_id INTEGER UNIQUE REFERENCES journals(id));
    CREATE TABLE IF NOT EXISTS accounts(code TEXT PRIMARY KEY,name TEXT NOT NULL,type TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS journal_lines(id INTEGER PRIMARY KEY,journal_id INTEGER NOT NULL REFERENCES journals(id),account TEXT NOT NULL REFERENCES accounts(code),debit INTEGER NOT NULL DEFAULT 0 CHECK(debit>=0),credit INTEGER NOT NULL DEFAULT 0 CHECK(credit>=0),party_id INTEGER REFERENCES parties(id),project_id INTEGER REFERENCES projects(id),CHECK((debit=0) OR (credit=0)));
    CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY,number TEXT UNIQUE,document_id INTEGER NOT NULL REFERENCES documents(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),date TEXT NOT NULL,reference TEXT,journal_id INTEGER REFERENCES journals(id));
    CREATE TABLE IF NOT EXISTS receipt_lines(id INTEGER PRIMARY KEY,receipt_id INTEGER NOT NULL REFERENCES receipts(id),source_line_id INTEGER NOT NULL REFERENCES document_lines(id),item_id INTEGER NOT NULL REFERENCES items(id),qty_milli INTEGER NOT NULL CHECK(qty_milli>0),value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS dispatches(id INTEGER PRIMARY KEY,number TEXT UNIQUE,document_id INTEGER NOT NULL REFERENCES documents(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),date TEXT NOT NULL,vehicle TEXT,transporter TEXT,pod_ref TEXT DEFAULT '',pod_date TEXT DEFAULT '',journal_id INTEGER REFERENCES journals(id));
    CREATE TABLE IF NOT EXISTS dispatch_lines(id INTEGER PRIMARY KEY,dispatch_id INTEGER NOT NULL REFERENCES dispatches(id),source_line_id INTEGER NOT NULL REFERENCES document_lines(id),item_id INTEGER NOT NULL REFERENCES items(id),qty_milli INTEGER NOT NULL CHECK(qty_milli>0),value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS stock_moves(id INTEGER PRIMARY KEY,date TEXT NOT NULL,item_id INTEGER NOT NULL REFERENCES items(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),qty_milli INTEGER NOT NULL,value INTEGER NOT NULL,source TEXT NOT NULL,source_id INTEGER,project_id INTEGER REFERENCES projects(id),notes TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,number TEXT UNIQUE,date TEXT NOT NULL,direction TEXT NOT NULL,party_id INTEGER NOT NULL REFERENCES parties(id),document_id INTEGER REFERENCES documents(id),bucket TEXT NOT NULL,cash INTEGER NOT NULL,tds INTEGER NOT NULL,retention INTEGER NOT NULL,advance_used INTEGER NOT NULL,reference TEXT,memo TEXT,journal_id INTEGER REFERENCES journals(id),reversal_id INTEGER REFERENCES journals(id));
    CREATE TABLE IF NOT EXISTS clearances(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),area TEXT NOT NULL,trade TEXT,status TEXT NOT NULL,required_date TEXT,cleared_date TEXT,blocked_by TEXT,owner TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS site_logs(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),date TEXT NOT NULL,team TEXT NOT NULL,headcount INTEGER NOT NULL,hours TEXT,daily_rate INTEGER NOT NULL,status TEXT NOT NULL,output_milli INTEGER NOT NULL,uom TEXT,notes TEXT,journal_id INTEGER REFERENCES journals(id),UNIQUE(project_id,date,team));
    CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),title TEXT NOT NULL,type TEXT NOT NULL,value INTEGER NOT NULL,status TEXT NOT NULL,owner TEXT,raised_date TEXT,reference TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS measurements(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),invoice_id INTEGER REFERENCES documents(id),date TEXT NOT NULL,zone TEXT NOT NULL,description TEXT NOT NULL,uom TEXT NOT NULL,executed_milli INTEGER NOT NULL,measured_milli INTEGER NOT NULL,certified_milli INTEGER NOT NULL,rate INTEGER NOT NULL,value INTEGER NOT NULL,status TEXT NOT NULL,owner TEXT,reference TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS credit_instruments(id INTEGER PRIMARY KEY,project_id INTEGER REFERENCES projects(id),party_id INTEGER NOT NULL REFERENCES parties(id),reference TEXT NOT NULL UNIQUE,bank TEXT NOT NULL,issue_date TEXT NOT NULL,due_date TEXT NOT NULL,face_value INTEGER NOT NULL,claim_value INTEGER NOT NULL,accepted_value INTEGER NOT NULL,status TEXT NOT NULL,owner TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,title TEXT NOT NULL,project_id INTEGER REFERENCES projects(id),owner TEXT,due_date TEXT,priority TEXT,status TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS attachments(id INTEGER PRIMARY KEY,entity TEXT NOT NULL,record_id INTEGER NOT NULL,filename TEXT NOT NULL,data BLOB NOT NULL,uploaded_by INTEGER REFERENCES users(id),timestamp TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,user_id INTEGER REFERENCES users(id),entity TEXT NOT NULL,record_id INTEGER,action TEXT NOT NULL,detail TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_docs_type ON documents(type,status);
    CREATE INDEX IF NOT EXISTS ix_jlines_account ON journal_lines(account,party_id,project_id);
    CREATE INDEX IF NOT EXISTS ix_stock_balance ON stock_moves(item_id,warehouse_id);
    CREATE INDEX IF NOT EXISTS ix_pay_doc ON payments(document_id);
    CREATE INDEX IF NOT EXISTS ix_lines_doc ON document_lines(document_id);
    ''')
    c.executemany('INSERT OR IGNORE INTO accounts VALUES (?,?,?)',ACCOUNTS)
    defaults={'company_name':'One Source','tagline':'Ceilings. Projects. Control.','address':'','gstin':'','state':'29','email':'','phone':'','locked_through':'','demo':False,'schema_version':1}
    for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,json.dumps(v)))
    password=None
    if not c.execute('SELECT 1 FROM users').fetchone():
        password=secrets.token_urlsafe(15)
        insert(c,'users',dict(username='admin',name='Sushanth / Administrator',role='admin',password=password_hash(password)))
    if not c.execute('SELECT 1 FROM warehouses').fetchone(): insert(c,'warehouses',dict(name='Bengaluru Central',city='Bengaluru'))
    c.close(); return password

def journal(c,user,dt,memo,source,source_id,lines,reverses=None):
    dt=check_period(c,dt)
    clean=[]
    for line in lines:
        a=str(line[0]); d=int(line[1]); cr=int(line[2]); party=line[3] if len(line)>3 else None; proj=line[4] if len(line)>4 else None
        need(d>=0 and cr>=0 and not(d and cr),'A journal line must have only one debit or credit.')
        need(c.execute('SELECT 1 FROM accounts WHERE code=?',(a,)).fetchone(),'Unknown ledger account.')
        if d or cr: clean.append((a,d,cr,party,proj))
    need(len(clean)>=2 and sum(x[1] for x in clean)==sum(x[2] for x in clean),'Journal debits and credits must balance and be non-zero.')
    jid=insert(c,'journals',dict(number=next_no(c,'JV',dt),date=dt,memo=text(memo),source=source,source_id=source_id,created_by=user['id'],reverses_id=reverses))
    for a,d,cr,party,proj in clean: insert(c,'journal_lines',dict(journal_id=jid,account=a,debit=d,credit=cr,party_id=party,project_id=proj))
    audit(c,user,'journals',jid,'post',{'memo':memo,'total':sum(x[1] for x in clean)})
    return jid

def reverse_journal(c,user,jid,dt,reason):
    orig=get(c,'journals',jid)
    need(not c.execute('SELECT 1 FROM journals WHERE reverses_id=?',(jid,)).fetchone(),'This journal is already reversed.')
    need(valid_date(dt)>=orig['date'],'Reversal cannot precede the original posting.')
    ls=rows(c,'SELECT * FROM journal_lines WHERE journal_id=?',(jid,))
    return journal(c,user,dt,'Reversal: '+orig['number']+' | '+reason,'reversal',jid,[(l['account'],l['credit'],l['debit'],l['party_id'],l['project_id']) for l in ls],jid)

def master_create(c,user,entity,p):
    if entity in ('parties','leads','tasks'): allowed(user,('sales','operations','accounts'))
    elif entity in ('items','warehouses','projects','clearances','site_logs','changes'): allowed(user,('operations','accounts'))
    else: raise RuleError('Unknown record type.')
    if entity=='parties':
        need(text(p.get('name')),'Name is required.'); need(p.get('type') in ('Customer','Supplier','Both'),'Choose customer or supplier.')
        v={k:text(p.get(k),2000 if k in ('address','notes') else 200) for k in ('name','type','email','phone','gstin','state','address','notes')}
        v['gstin']=v['gstin'].upper(); need(not v['gstin'] or len(v['gstin'])==15,'GSTIN must be 15 characters. Verify it independently.')
        v['credit_days']=int(p.get('credit_days',30)); need(0<=v['credit_days']<=730,'Invalid credit days.')
    elif entity=='items':
        v={k:text(p.get(k)) for k in ('sku','name','category','kind','uom','hsn')}; need(v['sku'] and v['name'] and v['uom'],'SKU, name and unit are required.')
        need(v['kind'] in ('Stock','Service'),'Choose Stock or Service.')
        v.update(sell_rate=money(p.get('sell_rate')),buy_rate=money(p.get('buy_rate')),gst_bps=num(p.get('gst_rate',18)),reorder_milli=quantity(p.get('reorder')))
        need(v['sell_rate']>=0 and v['buy_rate']>=0 and 0<=v['gst_bps']<=10000 and v['reorder_milli']>=0,'Rates and stock thresholds must be non-negative.')
    elif entity=='warehouses':
        v={'name':text(p.get('name')),'city':text(p.get('city'))}; need(v['name'],'Warehouse name required.')
    elif entity=='projects':
        v={k:text(p.get(k),2000) for k in ('code','name','city','scope','status','owner','notes')}; need(v['code'] and v['name'],'Project code and name required.')
        v['client_id']=int(p['client_id']); party=get(c,'parties',v['client_id']); need(party['type']!='Supplier','Project client must be a customer.')
        v.update(budget=money(p.get('budget')),area_milli=quantity(p.get('area')),start_date=valid_date(p.get('start_date',today())),target_date=valid_date(p.get('target_date',today())))
        need(v['budget']>=0 and v['area_milli']>=0,'Budget and area cannot be negative.'); need(v['status'] in ('Planning','Active','On hold','Completed'),'Invalid project status.')
    elif entity=='leads':
        v={k:text(p.get(k),2000) for k in ('company','contact','phone','scope','stage','owner','notes')}
        need(v['company'],'Company is required.'); need(v['stage'] in ('New','Qualified','Quoted','Negotiation','Won','Lost'),'Invalid lead stage.')
        v.update(value=money(p.get('value')),probability=int(p.get('probability',20)),next_date=valid_date(p.get('next_date',today())),party_id=int(p['party_id']) if p.get('party_id') else None)
        need(v['value']>=0 and 0<=v['probability']<=100,'Invalid lead value or probability.')
    elif entity=='clearances':
        v={k:text(p.get(k),2000) for k in ('area','trade','status','blocked_by','owner','notes')}; need(v['area'],'Area or floor is required.')
        v.update(project_id=int(p['project_id']),required_date=valid_date(p.get('required_date',today())),cleared_date='')
        need(v['status'] in ('Awaiting clearance','Cleared','Blocked','Completed'),'Invalid clearance status.')
        if v['status']=='Cleared': v['cleared_date']=today()
    elif entity=='site_logs':
        v={k:text(p.get(k),2000) for k in ('team','status','uom','notes')}; need(v['team'],'Team / contractor required.')
        need(v['status'] in ('Working','Idle','Rework'),'Invalid site status.')
        v.update(project_id=int(p['project_id']),date=valid_date(p.get('date',today())),headcount=int(p.get('headcount',0)),hours=str(p.get('hours','8')),daily_rate=money(p.get('daily_rate')),output_milli=quantity(p.get('output')))
        need(0<v['headcount']<=10000 and v['daily_rate']>=0 and v['output_milli']>=0 and 0<=float(v['hours'])<=24,'Check manpower, daily rate, hours and output.')
    elif entity=='changes':
        v={k:text(p.get(k),2000) for k in ('title','type','status','owner','reference','notes')}; need(v['title'],'Description required.')
        need(v['type'] in ('Variation','Rework','Rate difference','Debit dispute'),'Invalid change type.')
        need(v['status'] in ('Raised','Submitted','Approved','Rejected','Billed'),'Invalid change status.')
        v.update(project_id=int(p['project_id']),value=money(p.get('value')),raised_date=valid_date(p.get('raised_date',today())))
        need(v['value']>=0,'Value must be non-negative.')
        if v['status'] in ('Approved','Billed'): allowed(user,('accounts',))
    elif entity=='tasks':
        v={k:text(p.get(k),2000) for k in ('title','owner','priority','status','notes')}; need(v['title'],'Task title required.')
        v.update(project_id=int(p['project_id']) if p.get('project_id') else None,due_date=valid_date(p.get('due_date',today())))
        need(v['priority'] in ('High','Medium','Low') and v['status'] in ('Open','In progress','Done'),'Invalid task priority or status.')
    if v.get('project_id'): get(c,'projects',v['project_id'])
    id=insert(c,entity,v); audit(c,user,entity,id,'create',v); return {'id':id,'message':'Record created.'}

def operational_update(c,user,p):
    entity=p['entity']; id=int(p['id']); old=get(c,entity,id)
    configs={
        'leads':(('sales',),{'stage':('New','Qualified','Quoted','Negotiation','Won','Lost')},('next_date','owner','notes')),
        'tasks':(('sales','operations','accounts'),{'status':('Open','In progress','Done')},('owner','due_date','notes')),
        'clearances':(('operations',),{'status':('Awaiting clearance','Cleared','Blocked','Completed')},('blocked_by','notes','owner')),
        'changes':(('operations','accounts'),{'status':('Raised','Submitted','Approved','Rejected','Billed')},('reference','notes','owner')),
        'projects':(('operations',),{'status':('Planning','Active','On hold','Completed')},('target_date','owner','notes')),
        'dispatches':(('operations',),{},('pod_ref','pod_date')),
    }
    need(entity in configs,'This record cannot be edited. Posted accounting entries require reversal.')
    roles, enums, fields=configs[entity]; allowed(user,roles); v={}
    for k,opts in enums.items():
        if k in p: need(p[k] in opts,'Invalid status.'); v[k]=p[k]
    if entity=='changes' and v.get('status') in ('Approved','Billed'): allowed(user,('accounts',))
    for k in fields:
        if k in p: v[k]=valid_date(p[k]) if k.endswith('_date') and p[k] else text(p[k],2000)
    if entity=='clearances' and v.get('status') in ('Cleared','Completed'): v['cleared_date']=today()
    if entity=='clearances' and v.get('status') in ('Awaiting clearance','Blocked'): v['cleared_date']=''
    need(v,'No editable fields supplied.')
    c.execute(f"UPDATE {entity} SET "+','.join(k+'=?' for k in v)+' WHERE id=?',tuple(v.values())+(id,))
    audit(c,user,entity,id,'update',{'before':{k:old.get(k) for k in v},'after':v}); return {'id':id,'message':'Updated.'}

def calculate_line(c,p,mode):
    item=get(c,'items',p['item_id']); qty=quantity(p.get('qty')); rate=money(p.get('rate',item['sell_rate']/100)); gst=num(p.get('gst_rate',item['gst_bps']/100))
    need(qty>0 and rate>=0 and 0<=gst<=10000,'Quantity must be positive; rate and GST must be valid.')
    base=rounded(qty*rate); cgst=sgst=igst=0
    if mode=='intra': cgst=rounded(base*gst,20000); sgst=cgst
    elif mode=='inter': igst=rounded(base*gst,10000)
    return dict(item_id=item['id'],source_line_id=int(p['source_line_id']) if p.get('source_line_id') else None,description=text(p.get('description') or item['name']),qty_milli=qty,rate=rate,gst_bps=gst,base=base,cgst=cgst,sgst=sgst,igst=igst,total=base+cgst+sgst+igst)

def create_doc(c,user,p,internal=False):
    typ=p.get('type'); need(typ in DOC_TYPES,'Unknown document type.')
    if not internal: allowed(user,('accounts',) if typ in ('invoice','bill') else ('operations',) if typ=='purchase_order' else ('sales',))
    party=get(c,'parties',p['party_id']); need(party['type']!='Customer' if typ in ('purchase_order','bill') else party['type']!='Supplier','Party type does not match this document.')
    mode=p.get('tax_mode','intra'); need(mode in ('intra','inter','none'),'Select a tax mode.')
    dt=valid_date(p.get('date',today())); due=valid_date(p.get('due_date') or (date.fromisoformat(dt)+timedelta(days=party['credit_days'])).isoformat())
    source=int(p['source_id']) if p.get('source_id') else None; proj=int(p['project_id']) if p.get('project_id') else None
    receipt_id=int(p['receipt_id']) if p.get('receipt_id') else None
    if not internal:
        need(not source and not receipt_id,'Use the conversion workflow to link source documents.')
        need(not any(l.get('source_line_id') for l in p.get('lines',[])),'Use a linked conversion to specify source lines.')
    if proj: get(c,'projects',proj)
    need(isinstance(p.get('lines'),list) and 0<len(p['lines'])<=200,'Add between 1 and 200 line items.')
    ls=[calculate_line(c,l,mode) for l in p['lines']]
    if typ in ('invoice','bill') and not source:
        need(all(get(c,'items',l['item_id'])['kind']=='Service' for l in ls),'Stock invoices must come from sales orders; stock bills must come from goods receipts.')
    if typ=='purchase_order': need(all(get(c,'items',l['item_id'])['kind']=='Stock' for l in ls),'Use a direct service bill for subcontract / service purchases in this version.')
    totals={k:sum(l[k] for l in ls) for k in ('base','cgst','sgst','igst','total')}; need(totals['total']>0,'Document total must be positive.')
    if typ=='sales_order' and text(p.get('reference')):
        need(not c.execute("SELECT 1 FROM documents WHERE type='sales_order' AND party_id=? AND lower(trim(reference))=lower(trim(?)) AND status!='Cancelled'",(party['id'],text(p['reference']))).fetchone(),'A sales order already uses this client PO / WO reference.')
    id=insert(c,'documents',dict(number=next_no(c,PREFIX[typ],dt),type=typ,party_id=party['id'],project_id=proj,source_id=source,receipt_id=receipt_id,date=dt,due_date=due,reference=text(p.get('reference')),status='Draft',tax_mode=mode,place_of_supply=text(p.get('place_of_supply') or party['state']),notes=text(p.get('notes'),4000),created_by=user['id'],**totals))
    for l in ls: insert(c,'document_lines',dict(document_id=id,**l))
    audit(c,user,'documents',id,'create',{'type':typ,'total':totals['total']}); return {'id':id,'message':'Draft created. No accounting entry posted.'}

def doc_lines(c,id): return rows(c,'SELECT l.*,i.kind,i.uom,i.sku,i.hsn FROM document_lines l JOIN items i ON i.id=l.item_id WHERE document_id=?',(id,))
def invoiced_qty(c,line_id):
    return c.execute("SELECT COALESCE(SUM(l.qty_milli),0) FROM document_lines l JOIN documents d ON d.id=l.document_id WHERE l.source_line_id=? AND d.type='invoice' AND d.status='Posted'",(line_id,)).fetchone()[0]
def dispatched_qty(c,line_id): return c.execute('SELECT COALESCE(SUM(qty_milli),0) FROM dispatch_lines WHERE source_line_id=?',(line_id,)).fetchone()[0]
def received_qty(c,line_id): return c.execute('SELECT COALESCE(SUM(qty_milli),0) FROM receipt_lines WHERE source_line_id=?',(line_id,)).fetchone()[0]

def convert_doc(c,user,p):
    src=get(c,'documents',p['id']); target=p['target']
    if target=='sales_order':
        allowed(user,('sales',)); need(src['type']=='quote' and src['status']=='Approved','Approve the quotation before conversion.')
        need(not c.execute("SELECT 1 FROM documents WHERE source_id=? AND type='sales_order' AND status!='Cancelled'",(src['id'],)).fetchone(),'This quotation already has a sales order.')
    elif target=='invoice':
        allowed(user,('accounts',)); need(src['type']=='sales_order' and src['status']=='Approved','Invoice an approved sales order.')
    else: raise RuleError('Unsupported document conversion.')
    ls=[]
    requested={int(x['line_id']):quantity(x['qty']) for x in p.get('lines',[])}
    for l in doc_lines(c,src['id']):
        remaining=l['qty_milli']
        if target=='invoice': remaining=(dispatched_qty(c,l['id']) if l['kind']=='Stock' else l['qty_milli'])-invoiced_qty(c,l['id'])
        qty=requested.get(l['id'],remaining)
        need(0<=qty<=remaining,'Quantity exceeds the available, unbilled balance.')
        if qty: ls.append(dict(item_id=l['item_id'],source_line_id=l['id'],qty=qty/1000,rate=l['rate']/100,gst_rate=l['gst_bps']/100,description=l['description']))
    need(ls,'Nothing is available to convert. Dispatch material before raising a stock invoice.')
    res=create_doc(c,user,dict(type=target,party_id=src['party_id'],project_id=src['project_id'],source_id=src['id'],date=p.get('date',today()),due_date=p.get('due_date'),tax_mode=src['tax_mode'],place_of_supply=src['place_of_supply'],reference=src['reference'],notes=src['notes'],lines=ls),True)
    if target=='sales_order': c.execute("UPDATE documents SET status='Converted' WHERE id=?",(src['id'],))
    return res

def approve_doc(c,user,p):
    allowed(user,('accounts',)); d=get(c,'documents',p['id'])
    need(d['type'] in ('quote','sales_order','purchase_order') and d['status']=='Draft','Only draft quotations and orders can be approved.')
    c.execute("UPDATE documents SET status='Approved',approved_by=? WHERE id=?",(user['id'],d['id']))
    audit(c,user,'documents',d['id'],'approve',{}); return {'id':d['id'],'message':'Approved.'}

def post_doc(c,user,p):
    allowed(user,('accounts',)); d=get(c,'documents',p['id']); need(d['type'] in ('invoice','bill') and d['status']=='Draft','Only a draft invoice or bill can be posted.')
    check_period(c,d['date']); ls=doc_lines(c,d['id']); party=d['party_id']; proj=d['project_id']
    if d['source_id']:
        source=get(c,'documents',d['source_id']); need(source['status']=='Approved','Source order is no longer approved.')
    if d['type']=='invoice' and d['source_id']:
        # Aggregate by source line to prevent split-line overbilling.
        aggregate={}
        for l in ls:
            need(l['source_line_id'],'Missing order line reference.'); original=get(c,'document_lines',l['source_line_id'])
            need(original['document_id']==d['source_id'],'Invoice line does not belong to the source order.')
            aggregate[l['source_line_id']]=aggregate.get(l['source_line_id'],0)+l['qty_milli']
        for source_id,qty in aggregate.items():
            orig=get(c,'document_lines',source_id); item=get(c,'items',orig['item_id'])
            dated_dispatch=c.execute('SELECT COALESCE(SUM(l.qty_milli),0) FROM dispatch_lines l JOIN dispatches d ON d.id=l.dispatch_id WHERE l.source_line_id=? AND d.date<=?',(source_id,d['date'])).fetchone()[0]
            available=(dated_dispatch if item['kind']=='Stock' else orig['qty_milli'])-invoiced_qty(c,source_id)
            need(qty<=available,'This invoice would exceed dispatched / unbilled order quantities.')
    if d['type']=='bill':
        need(d['reference'],'Enter the supplier invoice reference before posting.')
        need(not c.execute("SELECT 1 FROM documents WHERE type='bill' AND party_id=? AND lower(trim(reference))=lower(trim(?)) AND status='Posted' AND id<>?",(party,d['reference'],d['id'])).fetchone(),'This supplier invoice reference is already posted.')
        if d['receipt_id']:
            need(not c.execute("SELECT 1 FROM documents WHERE receipt_id=? AND type='bill' AND status='Posted'",(d['receipt_id'],)).fetchone(),'This receipt is already billed.')
            receipt=get(c,'receipts',d['receipt_id']); need(d['date']>=receipt['date'],'Bill date cannot precede the goods-receipt date in this version.')
    entries=[]
    if d['type']=='invoice':
        entries.append(('1100',d['total'],0,party,proj))
        for l in ls: entries.append(('4000' if l['kind']=='Stock' else '4100',0,l['base'],party,proj))
        for k,a in [('cgst','2210'),('sgst','2220'),('igst','2230')]: entries.append((a,0,d[k],party,proj))
    else:
        entries.append(('2000',0,d['total'],party,proj))
        for l in ls: entries.append(('2010' if l['kind']=='Stock' else '5100',l['base'],0,party,proj))
        for k,a in [('cgst','1210'),('sgst','1220'),('igst','1230')]: entries.append((a,d[k],0,party,proj))
    jid=journal(c,user,d['date'],d['number']+' | '+d['reference'],d['type'],d['id'],entries)
    c.execute("UPDATE documents SET status='Posted',journal_id=?,approved_by=? WHERE id=?",(jid,user['id'],d['id']))
    audit(c,user,'documents',d['id'],'post',{'journal_id':jid}); return {'id':d['id'],'message':'Posted to the general ledger.'}

def stock_balance(c,item,warehouse):
    r=row(c,'SELECT COALESCE(SUM(qty_milli),0) qty,COALESCE(SUM(value),0) value FROM stock_moves WHERE item_id=? AND warehouse_id=?',(item,warehouse)); return r['qty'],r['value']
def stock_cost(c,item,warehouse,qty):
    onhand,value=stock_balance(c,item,warehouse); need(qty>0 and onhand>=qty,'Insufficient stock at this warehouse. Negative stock is blocked.')
    return value if qty==onhand else rounded(value*qty,onhand)

def receive(c,user,p):
    allowed(user,('operations',)); d=get(c,'documents',p['id']); need(d['type']=='purchase_order' and d['status']=='Approved','Receive against an approved purchase order.')
    dt=check_period(c,p.get('date',today())); need(dt>=d['date'],'Receipt cannot precede the purchase order.')
    wh=int(p['warehouse_id']); get(c,'warehouses',wh); requested={int(x['line_id']):quantity(x['qty']) for x in p.get('lines',[])}
    need(requested,'Enter received quantities.'); need(len(requested)==len(p['lines']),'Duplicate order lines are not allowed.')
    source={l['id']:l for l in doc_lines(c,d['id'])}; need(set(requested)<=set(source),'Invalid purchase order line.')
    entries=[]; total=0
    rid=insert(c,'receipts',dict(number=next_no(c,'GR',dt),document_id=d['id'],warehouse_id=wh,date=dt,reference=text(p.get('reference'))))
    for lid,qty in requested.items():
        need(qty>=0,'Received quantity cannot be negative.')
        if not qty: continue
        l=source[lid]; received=received_qty(c,lid); need(qty<=l['qty_milli']-received,'Receipt exceeds the unreceived PO quantity.')
        latest=c.execute('SELECT MAX(date) FROM stock_moves WHERE item_id=? AND warehouse_id=?',(l['item_id'],wh)).fetchone()[0]
        need(not latest or dt>=latest,'Backdated stock receipts are blocked after a later stock movement.')
        previous=c.execute('SELECT COALESCE(SUM(value),0) FROM receipt_lines WHERE source_line_id=?',(lid,)).fetchone()[0]
        value=l['base']-previous if qty+received==l['qty_milli'] else rounded(qty*l['rate'])
        insert(c,'receipt_lines',dict(receipt_id=rid,source_line_id=lid,item_id=l['item_id'],qty_milli=qty,value=value))
        insert(c,'stock_moves',dict(date=dt,item_id=l['item_id'],warehouse_id=wh,qty_milli=qty,value=value,source='receipt',source_id=rid,project_id=d['project_id'],notes=p.get('reference','')))
        total+=value
    need(total>0,'Receive at least one line with a non-zero value.')
    jid=journal(c,user,dt,f'Goods receipt for {d["number"]}','receipt',rid,[('1200',total,0,d['party_id'],d['project_id']),('2010',0,total,d['party_id'],d['project_id'])])
    c.execute('UPDATE receipts SET journal_id=? WHERE id=?',(jid,rid)); audit(c,user,'receipts',rid,'receive',{'value':total}); return {'id':rid,'message':'Stock received. Inventory and GRNI posted.'}

def bill_receipt(c,user,p):
    allowed(user,('accounts',)); rec=get(c,'receipts',p['id']); d=get(c,'documents',rec['document_id'])
    need(not c.execute("SELECT 1 FROM documents WHERE receipt_id=? AND status IN ('Draft','Posted')",(rec['id'],)).fetchone(),'A bill already exists for this receipt.')
    need(text(p.get('reference')),'Supplier invoice reference required.')
    ls=[]
    rls=rows(c,'SELECT r.*,l.rate,l.gst_bps,l.description FROM receipt_lines r JOIN document_lines l ON l.id=r.source_line_id WHERE receipt_id=?',(rec['id'],))
    for l in rls: ls.append(dict(item_id=l['item_id'],source_line_id=l['source_line_id'],qty=l['qty_milli']/1000,rate=l['rate']/100,gst_rate=l['gst_bps']/100,description=l['description']))
    result=create_doc(c,user,dict(type='bill',party_id=d['party_id'],project_id=d['project_id'],source_id=d['id'],receipt_id=rec['id'],date=p.get('date',today()),due_date=p.get('due_date'),reference=p['reference'],tax_mode=d['tax_mode'],place_of_supply=d['place_of_supply'],lines=ls),True)
    # Preserve exact receipt allocation, including final-paise rounding.
    for original,created in zip(rls,doc_lines(c,result['id'])):
        base=original['value']; cg=sg=ig=0
        if d['tax_mode']=='intra': cg=sg=rounded(base*created['gst_bps'],20000)
        elif d['tax_mode']=='inter': ig=rounded(base*created['gst_bps'],10000)
        c.execute('UPDATE document_lines SET base=?,cgst=?,sgst=?,igst=?,total=? WHERE id=?',(base,cg,sg,ig,base+cg+sg+ig,created['id']))
    sums=row(c,'SELECT SUM(base) base,SUM(cgst) cgst,SUM(sgst) sgst,SUM(igst) igst,SUM(total) total FROM document_lines WHERE document_id=?',(result['id'],))
    c.execute('UPDATE documents SET base=?,cgst=?,sgst=?,igst=?,total=? WHERE id=?',tuple(sums[k] for k in ('base','cgst','sgst','igst','total'))+(result['id'],))
    return result

def dispatch(c,user,p):
    allowed(user,('operations',)); d=get(c,'documents',p['id']); need(d['type']=='sales_order' and d['status']=='Approved','Dispatch against an approved sales order.')
    dt=check_period(c,p.get('date',today())); need(dt>=d['date'],'Dispatch cannot precede its order.')
    wh=int(p['warehouse_id']); get(c,'warehouses',wh); requested={int(x['line_id']):quantity(x['qty']) for x in p.get('lines',[])}
    need(requested and len(requested)==len(p.get('lines',[])),'Enter unique order lines.')
    source={l['id']:l for l in doc_lines(c,d['id'])}; need(set(requested)<=set(source),'Invalid sales-order line.')
    did=insert(c,'dispatches',dict(number=next_no(c,'DC',dt),document_id=d['id'],warehouse_id=wh,date=dt,vehicle=text(p.get('vehicle')),transporter=text(p.get('transporter'))))
    total=0; count=0
    for lid,qty in requested.items():
        need(qty>=0,'Dispatched quantity cannot be negative.')
        if not qty: continue
        l=source[lid]; need(l['kind']=='Stock','Only stock items can be dispatched.')
        need(qty<=l['qty_milli']-dispatched_qty(c,lid),'Dispatch exceeds remaining order quantity.')
        latest=c.execute('SELECT MAX(date) FROM stock_moves WHERE item_id=? AND warehouse_id=?',(l['item_id'],wh)).fetchone()[0]
        need(not latest or dt>=latest,'Backdated stock movements are blocked after a later movement.')
        value=stock_cost(c,l['item_id'],wh,qty)
        insert(c,'dispatch_lines',dict(dispatch_id=did,source_line_id=lid,item_id=l['item_id'],qty_milli=qty,value=value))
        insert(c,'stock_moves',dict(date=dt,item_id=l['item_id'],warehouse_id=wh,qty_milli=-qty,value=-value,source='dispatch',source_id=did,project_id=d['project_id'],notes=text(p.get('vehicle'))))
        total+=value; count+=1
    need(count>0,'Enter a positive dispatch quantity.')
    jid=journal(c,user,dt,f'Dispatch against {d["number"]}','dispatch',did,[('5000',total,0,d['party_id'],d['project_id']),('1200',0,total,d['party_id'],d['project_id'])]) if total else None
    c.execute('UPDATE dispatches SET journal_id=? WHERE id=?',(jid,did)); audit(c,user,'dispatches',did,'dispatch',{'cost':total}); return {'id':did,'message':'Dispatch saved. Stock and material cost updated.'}

def stock_action(c,user,p):
    action=p['action']; allowed(user,('operations',) if action=='transfer_stock' else ())
    item=get(c,'items',p['item_id']); need(item['kind']=='Stock','Select a stock item.')
    wh=int(p['warehouse_id']); get(c,'warehouses',wh); qty=quantity(p.get('qty')); need(qty>0,'Quantity must be positive.')
    dt=check_period(c,p.get('date',today())); latest=c.execute('SELECT MAX(date) FROM stock_moves WHERE item_id=? AND warehouse_id=?',(item['id'],wh)).fetchone()[0]
    need(not latest or dt>=latest,'Backdated stock movements are not supported.')
    if action=='opening_stock':
        rate=money(p.get('rate')); need(rate>=0,'Cost must not be negative.'); value=rounded(qty*rate)
        mid=insert(c,'stock_moves',dict(date=dt,item_id=item['id'],warehouse_id=wh,qty_milli=qty,value=value,source='opening',notes=text(p.get('notes'))))
        if value: journal(c,user,dt,'Opening stock | '+item['sku'],'opening_stock',mid,[('1200',value,0),('3000',0,value)])
    else:
        dest=int(p['to_warehouse_id']); get(c,'warehouses',dest); need(wh!=dest,'Choose a different destination warehouse.')
        latest_dest=c.execute('SELECT MAX(date) FROM stock_moves WHERE item_id=? AND warehouse_id=?',(item['id'],dest)).fetchone()[0]
        need(not latest_dest or dt>=latest_dest,'Transfer cannot precede a later destination movement.')
        value=stock_cost(c,item['id'],wh,qty)
        mid=insert(c,'stock_moves',dict(date=dt,item_id=item['id'],warehouse_id=wh,qty_milli=-qty,value=-value,source='transfer_out',notes=text(p.get('notes'))))
        insert(c,'stock_moves',dict(date=dt,item_id=item['id'],warehouse_id=dest,qty_milli=qty,value=value,source='transfer_in',source_id=mid,notes=text(p.get('notes'))))
    audit(c,user,'stock_moves',mid,action,{'qty_milli':qty,'value':value}); return {'id':mid,'message':'Stock movement recorded.'}

def payment_balances(c,docid):
    d=get(c,'documents',docid)
    p=row(c,"SELECT COALESCE(SUM(CASE WHEN bucket='trade' THEN cash+tds+retention+advance_used ELSE 0 END),0) settled,COALESCE(SUM(CASE WHEN bucket='trade' THEN retention WHEN bucket='retention' THEN -cash ELSE 0 END),0) retained FROM payments WHERE document_id=? AND reversal_id IS NULL",(docid,))
    return d['total']-p['settled'],p['retained']

def account_balance(c,code,party=None,as_of=None):
    sql='SELECT COALESCE(SUM(l.debit-l.credit),0) FROM journal_lines l JOIN journals j ON j.id=l.journal_id WHERE l.account=?'; args=[code]
    if party is not None: sql+=' AND l.party_id=?'; args.append(party)
    if as_of is not None: sql+=' AND j.date<=?'; args.append(as_of)
    return c.execute(sql,args).fetchone()[0]

def settle(c,user,p):
    allowed(user,('accounts',)); dt=check_period(c,p.get('date',today())); direction=p.get('direction'); need(direction in ('in','out'),'Choose receipt or payment.')
    bucket=p.get('bucket','trade'); need(bucket in ('trade','retention','advance'),'Invalid settlement bucket.')
    cash=money(p.get('cash')); tds=money(p.get('tds')); retained=money(p.get('retention')); advance=money(p.get('advance_used'))
    need(min(cash,tds,retained,advance)>=0 and cash+tds+retained+advance>0,'Enter positive settlement amounts.')
    docid=int(p['document_id']) if p.get('document_id') else None; proj=None
    if bucket=='advance':
        need(not docid and cash>0 and not (tds or retained or advance),'Advance entries accept only cash, without an invoice. Advance GST is not calculated.')
        party=get(c,'parties',p['party_id']); pid=party['id']; need(party['type']!='Supplier' if direction=='in' else party['type']!='Customer','Party type does not match advance direction.')
    else:
        need(docid,'Select an invoice / bill.'); d=get(c,'documents',docid); need(d['status']=='Posted','Settle a posted invoice / bill.')
        need(d['type']==('invoice' if direction=='in' else 'bill'),'Settlement direction does not match the document.')
        need(dt>=d['date'],'Settlement cannot precede the document date.')
        pid=d['party_id']; proj=d['project_id']; outstanding,held=payment_balances(c,docid)
        if bucket=='retention':
            dated_held=c.execute("SELECT COALESCE(SUM(CASE WHEN bucket='trade' THEN retention WHEN bucket='retention' THEN -cash ELSE 0 END),0) FROM payments WHERE document_id=? AND reversal_id IS NULL AND date<=?",(docid,dt)).fetchone()[0]
            need(cash<=min(held,dated_held) and not (tds or retained or advance),'Retention settlement must be cash only, within the retained balance on this date.')
        else: need(cash+tds+retained+advance<=outstanding,'Settlement exceeds the outstanding document amount.')
    if advance:
        available=(-1 if direction=='in' else 1)*account_balance(c,'2100' if direction=='in' else '1300',pid)
        dated_available=(-1 if direction=='in' else 1)*account_balance(c,'2100' if direction=='in' else '1300',pid,dt)
        need(advance<=min(available,dated_available),'Advance applied exceeds the available party advance on this date.')
    total=cash+tds+retained+advance
    if bucket=='advance':
        entries=[('1000',cash,0,pid,proj),('2100',0,cash,pid,proj)] if direction=='in' else [('1300',cash,0,pid,proj),('1000',0,cash,pid,proj)]
    elif bucket=='retention':
        entries=[('1000',cash,0,pid,proj),('1110',0,cash,pid,proj)] if direction=='in' else [('2020',cash,0,pid,proj),('1000',0,cash,pid,proj)]
    elif direction=='in': entries=[('1000',cash,0,pid,proj),('1120',tds,0,pid,proj),('1110',retained,0,pid,proj),('2100',advance,0,pid,proj),('1100',0,total,pid,proj)]
    else: entries=[('2000',total,0,pid,proj),('1000',0,cash,pid,proj),('2030',0,tds,pid,proj),('2020',0,retained,pid,proj),('1300',0,advance,pid,proj)]
    pay=insert(c,'payments',dict(number=next_no(c,'RC' if direction=='in' else 'PY',dt),date=dt,direction=direction,party_id=pid,document_id=docid,bucket=bucket,cash=cash,tds=tds,retention=retained,advance_used=advance,reference=text(p.get('reference')),memo=text(p.get('memo'))))
    jid=journal(c,user,dt,('Receipt ' if direction=='in' else 'Payment ')+text(p.get('reference')),'settlement',pay,entries)
    c.execute('UPDATE payments SET journal_id=? WHERE id=?',(jid,pay)); audit(c,user,'payments',pay,'post',{'cash':cash,'tds':tds,'retention':retained,'advance_used':advance})
    return {'id':pay,'message':'Settlement posted. Cash, deductions and outstanding updated.'}

def reverse_record(c,user,p):
    allowed(user,('accounts',)); entity=p['entity']; need(entity in ('documents','payments','journals'),'Only accounting records can be reversed here.')
    obj=get(c,entity,p['id']); reason=text(p.get('reason')); need(len(reason)>=5,'Record a clear reversal reason (at least 5 characters).')
    dt=valid_date(p.get('date',today()))
    if entity=='documents':
        need(obj['status']=='Posted' and obj['type'] in ('invoice','bill'),'Only posted invoices / bills can be reversed.')
        need(not c.execute("SELECT 1 FROM measurements WHERE invoice_id=? AND status='Billed'",(obj['id'],)).fetchone(),'Unlink billed measurement records before reversing the invoice.')
        need(not c.execute('SELECT 1 FROM payments WHERE document_id=? AND reversal_id IS NULL',(obj['id'],)).fetchone(),'Reverse all settlements on this document first.')
        jid=reverse_journal(c,user,obj['journal_id'],dt,reason); c.execute("UPDATE documents SET status='Reversed',reversal_id=? WHERE id=?",(jid,obj['id']))
    elif entity=='payments':
        need(not obj['reversal_id'],'This settlement is already reversed.')
        if obj['bucket']=='advance':
            available=(-1 if obj['direction']=='in' else 1)*account_balance(c,'2100' if obj['direction']=='in' else '1300',obj['party_id'])
            need(available>=obj['cash'],'Reverse advance applications first.')
        if obj['bucket']=='trade' and obj['retention']:
            _,held=payment_balances(c,obj['document_id']); need(held>=obj['retention'],'Reverse retention collections first.')
        jid=reverse_journal(c,user,obj['journal_id'],dt,reason); c.execute('UPDATE payments SET reversal_id=? WHERE id=?',(jid,obj['id']))
    else:
        need(obj['source']=='manual','Reverse operational postings at their originating record.')
        jid=reverse_journal(c,user,obj['id'],dt,reason)
    audit(c,user,entity,obj['id'],'reverse',{'reason':reason,'journal_id':jid}); return {'message':'Reversal posted; original entry retained in the audit trail.'}

def cancel_draft(c,user,p):
    d=get(c,'documents',p['id']); allowed(user,('accounts',) if d['type'] in ('invoice','bill') else ('operations',) if d['type']=='purchase_order' else ('sales',))
    need(d['status']=='Draft','Only drafts can be cancelled. Approved and posted records are preserved.')
    c.execute("UPDATE documents SET status='Cancelled' WHERE id=?",(d['id'],)); audit(c,user,'documents',d['id'],'cancel',{})
    return {'message':'Draft cancelled.'}

def command(c,user,p):
    """Caller MUST wrap this in a transaction; all validation failures roll back."""
    a=p.get('action')
    if a=='update_master': return update_master(c,user,p)
    if a=='toggle_user':
        allowed(user,()); target=get(c,'users',p['id']); active=int(p['active']); need(active in (0,1),'Invalid access state.')
        need(active or target['id']!=user['id'],'You cannot disable your own account.')
        c.execute('UPDATE users SET active=? WHERE id=?',(active,target['id']))
        if not active: c.execute('DELETE FROM sessions WHERE user_id=?',(target['id'],))
        audit(c,user,'users',target['id'],'enable' if active else 'disable',{})
        return {'message':'Team access updated.'}
    if a=='commercial_record': return commercial_record(c,user,p)
    if a=='create': return master_create(c,user,p['entity'],p)
    if a=='update': return operational_update(c,user,p)
    if a=='create_document': return create_doc(c,user,p)
    if a=='quote_from_lead':
        allowed(user,('sales',)); lead=get(c,'leads',p['lead_id'])
        need(not lead.get('quote_id'),'This opportunity already has a linked quotation.')
        res=create_doc(c,user,dict(p,type='quote'))
        c.execute("UPDATE leads SET quote_id=?,party_id=?,stage='Quoted' WHERE id=?",(res['id'],int(p['party_id']),lead['id']))
        audit(c,user,'leads',lead['id'],'quotation_created',{'quote_id':res['id']})
        return res
    if a=='approve_document': return approve_doc(c,user,p)
    if a=='convert_document': return convert_doc(c,user,p)
    if a=='post_document': return post_doc(c,user,p)
    if a=='cancel_draft': return cancel_draft(c,user,p)
    if a=='receive': return receive(c,user,p)
    if a=='bill_receipt': return bill_receipt(c,user,p)
    if a=='dispatch': return dispatch(c,user,p)
    if a in ('opening_stock','transfer_stock'): return stock_action(c,user,p)
    if a=='settle': return settle(c,user,p)
    if a=='reverse': return reverse_record(c,user,p)
    if a=='post_labour':
        allowed(user,('accounts',)); log=get(c,'site_logs',p['id']); need(not log['journal_id'],'This labour log is already accrued.')
        amount=log['headcount']*log['daily_rate']; need(amount>0,'Enter a positive daily rate. Cost is headcount x daily rate, not hourly.')
        jid=journal(c,user,log['date'],f'Labour: {log["team"]} ({log["status"]})','labour',log['id'],[('5200',amount,0,None,log['project_id']),('2040',0,amount,None,log['project_id'])])
        c.execute('UPDATE site_logs SET journal_id=? WHERE id=?',(jid,log['id'])); return {'message':'Labour cost accrued to the project and labour payable.'}
    if a=='manual_journal':
        allowed(user,('accounts',)); need(len(p.get('lines',[]))>=2,'Add at least two journal lines.')
        # Control accounts use document workflows to preserve subledger reconciliation.
        restricted={'1100','1110','1200','1300','2000','2010','2020','2100'}
        ls=[]
        for l in p['lines']:
            need(str(l['account']) not in restricted,'Use the originating document workflow for control accounts (AR, AP, stock, advances, retention and GRNI).')
            ls.append((l['account'],money(l.get('debit')),money(l.get('credit')),int(p['party_id']) if p.get('party_id') else None,int(p['project_id']) if p.get('project_id') else None))
        jid=journal(c,user,p.get('date',today()),text(p.get('memo')),'manual',None,ls); return {'id':jid,'message':'Balanced journal posted.'}
    if a=='save_settings':
        allowed(user,()); keys=('company_name','tagline','address','gstin','state','email','phone','locked_through')
        old=settings(c)
        for k in keys:
            if k not in p: continue
            v=text(p[k],2000)
            if k=='company_name': need(v,'Company name is required.')
            if k=='gstin': need(not v or len(v)==15,'GSTIN must be 15 characters. Verify separately.'); v=v.upper()
            if k=='locked_through':
                if v: v=valid_date(v); need(v<=today(),'Cannot lock a future period.')
                need(not old.get(k) or v>=old[k],'A locked period cannot be reopened in this starter.')
            set_setting(c,k,v)
        audit(c,user,'settings',0,'update',{k:p[k] for k in keys if k in p}); return {'message':'Company settings saved.'}
    if a=='create_user':
        allowed(user,()); need(p.get('role') in ROLES,'Invalid user role.'); need(len(p.get('password',''))>=12,'Use a password of at least 12 characters.')
        un=text(p.get('username')).lower(); need(un and ' ' not in un,'Use a username without spaces.')
        uid=insert(c,'users',dict(username=un,name=text(p.get('name') or un),role=p['role'],password=password_hash(p['password'])))
        audit(c,user,'users',uid,'create',{'username':un,'role':p['role']}); return {'message':'User created.'}
    if a=='change_password':
        u=get(c,'users',user['id']); need(password_ok(p.get('current_password',''),u['password']),'Current password is incorrect.'); need(len(p.get('new_password',''))>=12,'Use a password of at least 12 characters.')
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(p['new_password']),u['id'])); c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
        audit(c,user,'users',u['id'],'password_change',{}); return {'message':'Password changed. Sign in again.','reauth':True}
    raise RuleError('Unknown action.')

def report_data(c):
    tb=rows(c,'''SELECT a.code,a.name,a.type,COALESCE(SUM(l.debit),0) debit,COALESCE(SUM(l.credit),0) credit,COALESCE(SUM(l.debit-l.credit),0) balance FROM accounts a LEFT JOIN journal_lines l ON l.account=a.code GROUP BY a.code ORDER BY a.code''')
    rev=-sum(x['balance'] for x in tb if x['type']=='Revenue'); exp=sum(x['balance'] for x in tb if x['type']=='Expense')
    assets=sum(x['balance'] for x in tb if x['type']=='Asset'); liabilities=-sum(x['balance'] for x in tb if x['type']=='Liability'); equity=-sum(x['balance'] for x in tb if x['type']=='Equity')
    imbalance=rows(c,'SELECT j.id,j.number,SUM(l.debit-l.credit) difference FROM journals j JOIN journal_lines l ON l.journal_id=j.id GROUP BY j.id HAVING difference<>0')
    inventory=c.execute('SELECT COALESCE(SUM(value),0) FROM stock_moves').fetchone()[0]
    ar=c.execute("SELECT COALESCE(SUM(total),0) FROM documents WHERE type='invoice' AND status='Posted'").fetchone()[0]-c.execute("SELECT COALESCE(SUM(cash+tds+retention+advance_used),0) FROM payments WHERE direction='in' AND bucket='trade' AND reversal_id IS NULL").fetchone()[0]
    ap=c.execute("SELECT COALESCE(SUM(total),0) FROM documents WHERE type='bill' AND status='Posted'").fetchone()[0]-c.execute("SELECT COALESCE(SUM(cash+tds+retention+advance_used),0) FROM payments WHERE direction='out' AND bucket='trade' AND reversal_id IS NULL").fetchone()[0]
    return {'trial_balance':tb,'revenue':rev,'expenses':exp,'profit':rev-exp,'assets':assets,'liabilities':liabilities,'equity':equity,'bank':account_balance(c,'1000'),'checks':{'journals_balanced':not imbalance,'trial_difference':sum(x['balance'] for x in tb),'stock_difference':inventory-account_balance(c,'1200'),'ar_difference':ar-account_balance(c,'1100'),'ap_difference':ap+account_balance(c,'2000'),'balance_sheet_difference':assets-liabilities-equity-(rev-exp)},'basis':'All posted entries to date; INR; no fiscal-year close or statutory adjustments.'}

def snapshot(c,user):
    result={'settings':settings(c),'user':{k:user[k] for k in ('id','username','name','role')},'today':today()}
    for t in ('parties','items','warehouses','projects','leads','documents','clearances','site_logs','changes','tasks','receipts','dispatches','payments','accounts','measurements','credit_instruments'):
        result[t]=rows(c,f'SELECT * FROM {t} ORDER BY '+('code' if t=='accounts' else 'id DESC'))
    result['document_lines']=rows(c,'SELECT l.*,i.kind,i.uom,i.sku,i.hsn FROM document_lines l JOIN items i ON i.id=l.item_id ORDER BY l.id')
    for l in result['document_lines']:
        l['dispatched_milli']=dispatched_qty(c,l['id']); l['received_milli']=received_qty(c,l['id']); l['invoiced_milli']=invoiced_qty(c,l['id'])
    for d in result['documents']:
        d['outstanding'],d['retained']=payment_balances(c,d['id']) if d['type'] in ('invoice','bill') and d['status']=='Posted' else (0,0)
    result['receipt_lines']=rows(c,'SELECT * FROM receipt_lines'); result['dispatch_lines']=rows(c,'SELECT * FROM dispatch_lines')
    result['stock']=rows(c,'''SELECT i.id item_id,i.sku,i.name,i.uom,i.reorder_milli,w.id warehouse_id,w.name warehouse,COALESCE(SUM(s.qty_milli),0) qty_milli,COALESCE(SUM(s.value),0) value FROM items i CROSS JOIN warehouses w LEFT JOIN stock_moves s ON s.item_id=i.id AND s.warehouse_id=w.id WHERE i.kind='Stock' GROUP BY i.id,w.id ORDER BY i.name,w.name''')
    result['stock_moves']=rows(c,'SELECT * FROM stock_moves ORDER BY date DESC,id DESC LIMIT 500')
    result['journals']=rows(c,'SELECT j.*,u.name user_name, (SELECT SUM(debit) FROM journal_lines l WHERE l.journal_id=j.id) amount FROM journals j LEFT JOIN users u ON u.id=j.created_by ORDER BY j.date DESC,j.id DESC')
    result['journal_lines']=rows(c,'SELECT * FROM journal_lines ORDER BY id')
    result['attachments']=rows(c,'SELECT id,entity,record_id,filename,uploaded_by,timestamp,length(data) size FROM attachments ORDER BY id DESC')
    result['audit']=rows(c,'SELECT a.*,u.name user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300')
    result['users']=rows(c,'SELECT id,username,name,role,active FROM users') if user['role']=='admin' else []
    result['reports']=report_data(c)
    for project in result['projects']:
        pid=project['id']; ls=rows(c,'SELECT a.type,COALESCE(SUM(l.debit-l.credit),0) amount FROM journal_lines l JOIN accounts a ON a.code=l.account WHERE project_id=? GROUP BY a.type',(pid,))
        project['revenue']=-sum(x['amount'] for x in ls if x['type']=='Revenue'); project['cost']=sum(x['amount'] for x in ls if x['type']=='Expense'); project['profit']=project['revenue']-project['cost']
    return result


def commercial_record(c,user,p):
    entity=p.get('entity'); need(entity in ('measurements','credit_instruments'),'Invalid commercial register.')
    allowed(user,('operations','accounts'))
    old=get(c,entity,p['id']) if p.get('id') else None
    if entity=='measurements':
        if old and old['status'] in ('Certified','Billed'): allowed(user,('accounts',))
        pid=int(p['project_id']); get(c,'projects',pid)
        status=p.get('status','Draft'); need(status in ('Draft','Submitted','Certified','Billed'),'Invalid measurement status.')
        if status in ('Certified','Billed'): allowed(user,('accounts',))
        ex=quantity(p.get('executed')); me=quantity(p.get('measured')); ce=quantity(p.get('certified')); rate=money(p.get('rate'))
        need(0<=ce<=me<=ex and rate>=0,'Certified quantity cannot exceed measured quantity; measured cannot exceed executed.')
        if ce: allowed(user,('accounts',))
        invoice_id=int(p['invoice_id']) if p.get('invoice_id') else None
        value=rounded(ce*rate)
        if status=='Billed':
            need(invoice_id,'Link the posted invoice for a Billed measurement.')
            inv=get(c,'documents',invoice_id)
            need(inv['type']=='invoice' and inv['status']=='Posted' and inv['project_id']==pid,'Select a posted invoice for this project.')
            other=c.execute("SELECT COALESCE(SUM(value),0) FROM measurements WHERE invoice_id=? AND status='Billed' AND id<>?",(invoice_id,old['id'] if old else 0)).fetchone()[0]
            need(value+other<=inv['base'],'Billed certified value exceeds the linked invoice taxable value.')
        else: invoice_id=None
        v=dict(project_id=pid,invoice_id=invoice_id,date=valid_date(p.get('date',today())),zone=text(p.get('zone')),description=text(p.get('description')),uom=text(p.get('uom','SQM')),executed_milli=ex,measured_milli=me,certified_milli=ce,rate=rate,value=value,status=status,owner=text(p.get('owner')),reference=text(p.get('reference')),notes=text(p.get('notes'),2000))
        need(v['zone'] and v['description'] and v['uom'],'Zone, work description and unit are required.')
    else:
        allowed(user,('accounts',))
        party=get(c,'parties',p['party_id']); need(party['type']!='Supplier','LC register is for customer collections.')
        pid=int(p['project_id']) if p.get('project_id') else None
        if pid: need(get(c,'projects',pid)['client_id']==party['id'],'Project customer must match the LC customer.')
        face=money(p.get('face_value')); claim=money(p.get('claim_value')); accepted=money(p.get('accepted_value'))
        need(0<=accepted<=claim<=face and face>0,'Accepted value must not exceed claimed value or LC face value.')
        status=p.get('status','Proposed'); need(status in ('Proposed','Issued','Submitted','Accepted','Discounted','Settled','Expired'),'Invalid LC status.')
        v=dict(project_id=pid,party_id=party['id'],reference=text(p.get('reference')),bank=text(p.get('bank')),issue_date=valid_date(p.get('issue_date',today())),due_date=valid_date(p.get('due_date',today())),face_value=face,claim_value=claim,accepted_value=accepted,status=status,owner=text(p.get('owner')),notes=text(p.get('notes'),2000))
        need(v['reference'] and v['bank'],'LC reference and issuing bank are required.')
        need(v['due_date']>=v['issue_date'],'Maturity cannot precede issue date.')
    if old:
        id=old['id']; c.execute(f"UPDATE {entity} SET "+','.join(k+'=?' for k in v)+' WHERE id=?',tuple(v.values())+(id,))
    else: id=insert(c,entity,v)
    audit(c,user,entity,id,'update' if old else 'create',v)
    return {'id':id,'message':'Commercial register saved. No accounting entry created.'}


def update_master(c,user,p):
    entity=p.get('entity'); need(entity in ('parties','items'),'Only contact and item masters can be edited here.')
    old=get(c,entity,p['id'])
    if entity=='parties':
        allowed(user,('sales','operations','accounts'))
        v={k:text(p.get(k,old[k]),2000 if k in ('address','notes') else 200) for k in ('name','type','email','phone','gstin','state','address','notes')}
        need(v['name'] and v['type'] in ('Customer','Supplier','Both'),'Name and valid party type required.')
        v['gstin']=v['gstin'].upper(); need(not v['gstin'] or len(v['gstin'])==15,'GSTIN must be 15 characters; verify separately.')
        v['credit_days']=int(p.get('credit_days',old['credit_days'])); need(0<=v['credit_days']<=730,'Invalid credit days.')
        if c.execute('SELECT 1 FROM documents WHERE party_id=?',(old['id'],)).fetchone(): need(v['type']==old['type'] or v['type']=='Both','A party with transactions cannot lose its existing customer / supplier role.')
    else:
        allowed(user,('operations','accounts'))
        v={k:text(p.get(k,old[k])) for k in ('sku','name','category','kind','uom','hsn')}
        need(v['sku'] and v['name'] and v['uom'] and v['kind'] in ('Stock','Service'),'Valid SKU, name, item type and unit required.')
        used=c.execute('SELECT 1 FROM document_lines WHERE item_id=? UNION ALL SELECT 1 FROM stock_moves WHERE item_id=? LIMIT 1',(old['id'],old['id'])).fetchone()
        if used: need(all(v[k]==old[k] for k in ('sku','kind','uom')),'SKU, unit and stock/service type cannot change after the item has transactions.')
        v.update(sell_rate=money(p.get('sell_rate',old['sell_rate']/100)),buy_rate=money(p.get('buy_rate',old['buy_rate']/100)),gst_bps=num(p.get('gst_rate',old['gst_bps']/100)),reorder_milli=quantity(p.get('reorder',old['reorder_milli']/1000)))
        need(v['sell_rate']>=0 and v['buy_rate']>=0 and 0<=v['gst_bps']<=10000 and v['reorder_milli']>=0,'Invalid rates or reorder threshold.')
    c.execute(f"UPDATE {entity} SET "+','.join(k+'=?' for k in v)+' WHERE id=?',tuple(v.values())+(old['id'],))
    audit(c,user,entity,old['id'],'update',{'before':{k:old[k] for k in v},'after':v})
    return {'id':old['id'],'message':'Master updated. Existing document amounts are unchanged.'}

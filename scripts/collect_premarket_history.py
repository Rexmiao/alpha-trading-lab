"""Bounded foreground moomoo 1m history capture for a fixed ETF event study.

No account, order, upload, scheduler, or paid-data operation is implemented.
First use --probe; resume the immutable pages with --resume <printed folder>.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import subprocess,sys,time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.audit_moomoo_option_data import credential,local_host,quote_envelope,utc_now
SYMBOLS=('QQQ','SPY')
ALLOWED_SYMBOLS=('QQQ','SPY','DIA')
BEGIN='2025-11-20'
END='2026-11-27'
TARGET_START='2025-11-27'
OUTPUT=ROOT/'data/premarket-history'
MAX_PAGES=500
MAX_ROWS=500_000

def digest(b):return hashlib.sha256(b).hexdigest()
def save(p,value):
    # Append immutable checkpoints: sync software can hold the initial manifest
    # against replacement even when new files remain writable.
    journal=p.parent/'progress'
    journal.mkdir(exist_ok=True)
    record=journal/f'{time.time_ns():020d}.json'
    with record.open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)
    if not p.exists():
        with p.open('x',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2)

def load_capture_manifest(folder):
    records=sorted((folder/'progress').glob('*.json')) if (folder/'progress').is_dir() else []
    return json.loads((records[-1] if records else folder/'manifest.json').read_text(encoding='utf-8'))

def validate_symbols(values):
    if (not isinstance(values,(list,tuple)) or not values
        or any(s not in ALLOWED_SYMBOLS for s in values) or len(set(values))!=len(values)):
        raise ValueError('capture_symbol_scope')
    return tuple(values)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',action='store_true')
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--page-size',type=int,default=5000,choices=[1000,5000])
    parser.add_argument('--symbols',nargs='+',choices=ALLOWED_SYMBOLS,
                        help='New capture subset; default QQQ SPY. Resume defaults to its saved symbols.')
    args=parser.parse_args(argv)
    requested=validate_symbols(args.symbols) if args.symbols is not None else None
    if args.resume:
        folder=args.resume.resolve()
        if OUTPUT.resolve() not in folder.parents:raise ValueError('output_scope')
        manifest=load_capture_manifest(folder)
        symbols=validate_symbols(manifest.get('symbols'))
        if (requested is not None and requested!=symbols):raise ValueError('resume_symbol_scope')
        if (set(manifest.get('streams',{}))!=set(symbols) or manifest['begin']!=BEGIN or manifest['end_exclusive']!=END
            or manifest['session']!='ALL' or manifest['rehab_type']!=0):raise ValueError('resume_scope')
        for symbol in symbols:
            for rec in manifest['streams'][symbol]['pages']:
                if digest((folder/rec['file']).read_bytes())!=rec['sha256']:raise ValueError('stored_page_hash')
    else:
        symbols=requested or SYMBOLS
        folder=OUTPUT/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder.mkdir(parents=True,exist_ok=False)
        manifest={'version':1,'source':'moomoo_desktop_history','symbols':list(symbols),
          'target_start':TARGET_START,'target_end_exclusive':END,'target_calendar_days':365,
          'today_excluded':True,'begin':BEGIN,'end_exclusive':END,'interval':'1m','session':'ALL',
          'rehab_type':0,'read_only':True,'account_requests':0,'orders':0,'paid_data':False,
          'started_at':utc_now(),'streams':{s:{'pages':[],'complete_pagination':False,'rows':0} for s in symbols},
          'collector_sha256':digest(Path(__file__).read_bytes()),'errors':[]}
        (folder/'collector-used.py').write_bytes(Path(__file__).read_bytes())
        save(folder/'manifest.json',manifest)
    run_file='collector-run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.py'
    code=Path(__file__).read_bytes()
    with (folder/run_file).open('xb') as f:f.write(code)
    manifest.setdefault('collector_runs',[]).append({'source':run_file,'sha256':digest(code),'started_at':utc_now()})
    save(folder/'manifest.json',manifest)
    key=credential()
    env=dict(os.environ,OPENAPI_HOST_URL=local_host('http://127.0.0.1:22222'),OPENAPI_HOST_APPKEY=key)
    cli=Path(os.environ.get('APPDATA',''))/'moomoo/2.0/OpenAPI/moomooapp-cli.exe'
    failed=False;last_call=0.
    for symbol in symbols:
        stream=manifest['streams'][symbol]
        if stream['complete_pagination']:continue
        cursor=stream['pages'][-1].get('next_req_key') if stream['pages'] else None
        seen={r.get('next_req_key') for r in stream['pages'] if r.get('next_req_key')}
        requests_this_stream=0
        while len(stream['pages'])<MAX_PAGES:
            if args.probe and requests_this_stream>=1:break
            time.sleep(max(0.,.65-(time.monotonic()-last_call)));last_call=time.monotonic()
            page=len(stream['pages'])+1
            flags=['--raw','request-history-kl','--rehab-type','0','--kl-type','1',
              '--begin-time',BEGIN,'--end-time',END,'--max-ack-kl-num',str(args.page_size),
              '--session','all','--extended-time']
            if cursor:flags+=['--next-req-key',cursor]
            flags+=['--symbol','US.'+symbol]
            rec={'page':page,'requested_at':utc_now(),'requested_page_size':args.page_size}
            try:
                p=subprocess.run([str(cli),*flags],env=env,capture_output=True,timeout=25,
                   stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                rec['received_at']=utc_now()
                if len(p.stdout)+len(p.stderr)>8_000_000:raise ValueError('response_byte_bound')
                data,failure=quote_envelope(p.stdout,p.stderr,p.returncode)
                if failure:
                    manifest['errors'].append({'symbol':symbol,'page':page,**failure});failed=True;break
                rows=data.get('kl_list')
                if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError('invalid_rows')
                nxt=data.get('next_req_key')
                if nxt and (not isinstance(nxt,str) or nxt in seen):raise ValueError('cursor_not_progressing')
                if stream['rows']+len(rows)>MAX_ROWS:raise ValueError('row_bound')
                filename=f'{symbol}-{page:04d}.json'
                raw=json.dumps({'ret_type':0,'s2c':data},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                with (folder/filename).open('xb') as f:f.write(raw)
                rec.update(file=filename,sha256=digest(raw),bytes=len(raw),rows=len(rows),
                   first_time=rows[0].get('time') if rows else None,last_time=rows[-1].get('time') if rows else None,
                   next_req_key=nxt,archive_format='reserialized_quote_s2c_json')
                stream['pages'].append(rec);stream['rows']+=len(rows);requests_this_stream+=1
                stream['complete_pagination']=not bool(nxt)
                manifest['updated_at']=utc_now();save(folder/'manifest.json',manifest)
                if page%10==0 or args.probe or not nxt:
                    print(json.dumps({'symbol':symbol,'pages':page,'rows':stream['rows'],'last_time':rec['last_time'],
                       'complete_pagination':stream['complete_pagination']},ensure_ascii=False),flush=True)
                if not nxt:break
                seen.add(nxt);cursor=nxt
            except Exception as exc:
                manifest['errors'].append({'symbol':symbol,'page':page,'error_type':type(exc).__name__});failed=True;break
        if len(stream['pages'])==MAX_PAGES and not stream['complete_pagination']:
            manifest['errors'].append({'symbol':symbol,'error_type':'PAGE_BOUND'});failed=True
        save(folder/'manifest.json',manifest)
    manifest['finished_at']=utc_now();manifest['complete']=all(s['complete_pagination'] for s in manifest['streams'].values())
    save(folder/'manifest.json',manifest)
    print(json.dumps({'folder':str(folder),'complete':manifest['complete'],'errors':manifest['errors'],
      'streams':{s:{k:v for k,v in manifest['streams'][s].items() if k!='pages'} for s in symbols}},ensure_ascii=False),flush=True)
    return 1 if failed else 0

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())

// Only completed market-history observations are exported. No brokerage API exists here.
import {spawn} from 'node:child_process';
import {existsSync,readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const config=JSON.parse(readFileSync(join(root,'config.json'),'utf8'));
const allowed=new Set(['subscribe','get-kline']);
const host=process.env.OPENAPI_HOST_URL||'http://127.0.0.1:22222';
const hostUrl=new URL(host);
if(!['127.0.0.1','localhost','[::1]'].includes(hostUrl.hostname)||!['http:','https:'].includes(hostUrl.protocol)||hostUrl.username||hostUrl.password||hostUrl.search||hostUrl.hash||!['','/'].includes(hostUrl.pathname))throw Error('Only local moomoo hosts are supported.');
const cli=process.env.ALPHA_MOOMOO_CLI||join(process.env.APPDATA||'', 'moomoo','2.0','OpenAPI','moomooapp-cli.exe');

function child(exe,args,{env=process.env,timeout=20000}={}) {
  return new Promise((resolveChild,reject)=>{
    const p=spawn(exe,args,{env,windowsHide:true,shell:false,stdio:['ignore','pipe','pipe']});
    let out='',bytes=0,done=false;
    const finish=(err,val)=>{if(done)return;done=true;clearTimeout(timer);err?reject(err):resolveChild(val);};
    const timer=setTimeout(()=>{p.kill();finish(Error('LOCAL_REQUEST_TIMEOUT'));},timeout);
    p.stdout.on('data',b=>{bytes+=b.length;if(bytes>8000000){p.kill();finish(Error('RESPONSE_TOO_LARGE'));}else out+=b.toString('utf8');});
    p.stderr.resume(); // Never log CLI/provider stderr or authentication material.
    p.on('error',()=>finish(Error('CLI_UNAVAILABLE')));
    p.on('close',code=>finish(null,{code,out}));
  });
}
async function keyFromProtectedStore() {
  if(process.env.OPENAPI_HOST_APPKEY)return process.env.OPENAPI_HOST_APPKEY.trim();
  if(process.platform!=='win32'||!process.env.LOCALAPPDATA)return '';
  const protectedPath=join(process.env.LOCALAPPDATA,'PcrMarketWatch','moomoo-appkey.dpapi');
  if(!existsSync(protectedPath))return '';
  const command='$ErrorActionPreference="Stop"; $encoded=Get-Content -LiteralPath $env:ALPHA_PROTECTED_KEY_PATH -Raw; $value=ConvertTo-SecureString $encoded; $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($value); try { [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }';
  const result=await child('powershell.exe',['-NoProfile','-NonInteractive','-Command',command],{env:{...process.env,ALPHA_PROTECTED_KEY_PATH:protectedPath,PSModulePath:join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','Modules')},timeout:10000});
  if(result.code!==0)throw Error('PROTECTED_CREDENTIAL_UNAVAILABLE');
  return result.out.trim();
}
function publicFailure(error) {
  const codes=new Set(['LOCAL_REQUEST_TIMEOUT','RESPONSE_TOO_LARGE','CLI_UNAVAILABLE','PROTECTED_CREDENTIAL_UNAVAILABLE','NOT_CONFIGURED','INVALID_RESPONSE','PROVIDER_REJECTED','AUTH_OR_PERMISSION','LOCAL_SERVICE_UNAVAILABLE']);
  return codes.has(error?.message)?error.message:'LOCAL_SERVICE_UNAVAILABLE';
}
const manifest={source:'moomoo',collected_at:new Date().toISOString(),host_scope:'loopback',read_only:true,requested_bars:config.bars,rehab_type:config.rehab_type,files:[],errors:[]};
try {
  const key=await keyFromProtectedStore();
  if(process.argv.includes('--probe')) {
    process.stdout.write(JSON.stringify({configured:Boolean(key),cli_available:existsSync(cli),read_only:true}));
    process.exit(0);
  }
  if(!key)throw Error('NOT_CONFIGURED');
  if(!existsSync(cli))throw Error('CLI_UNAVAILABLE');
  let lastCallAt=0;
  async function call(command,args) {
    if(!allowed.has(command))throw Error('PROVIDER_REJECTED');
    const wait=Math.max(0,700-(Date.now()-lastCallAt));
    if(wait)await new Promise(accept=>setTimeout(accept,wait));
    lastCallAt=Date.now();
    const result=await child(cli,['--raw',command,...args],{env:{...process.env,OPENAPI_HOST_URL:host,OPENAPI_HOST_APPKEY:key}});
    let payload;
    try {payload=JSON.parse(result.out.replace(/^\uFEFF/,''));}catch {throw Error('LOCAL_SERVICE_UNAVAILABLE');}
    if(result.code!==0||payload.ret_type!==0||!payload.s2c){
      const text=String(payload.ret_msg||'');
      throw Error(/key|auth|permission|权限|认证|鉴权/i.test(text)?'AUTH_OR_PERMISSION':'PROVIDER_REJECTED');
    }
    return payload.s2c;
  }
  const stamp=manifest.collected_at.replace(/[:.]/g,'-');
  const dir=join(root,'data','raw',stamp);mkdirSync(dir,{recursive:true});
  const symbols=[...new Set([...config.universe,config.benchmark])];
  if(symbols.some(symbol=>!/^[A-Z][A-Z0-9.]{0,9}$/.test(symbol)))throw Error('PROVIDER_REJECTED');
  // Subscribe in small batches; all commands remain within the market-data whitelist.
  const subscribed=new Set();
  for(let offset=0;offset<symbols.length;offset+=20) {
    const batch=symbols.slice(offset,offset+20);
    try {
      await call('subscribe',['--sub-type-list','kl_day','--is-sub-or-un-sub','--no-is-reg-or-un-reg-push','--extended-time','--session','all',...batch.map(symbol=>'US.'+symbol)]);
      batch.forEach(symbol=>subscribed.add(symbol));
    } catch(error) {
      batch.forEach(symbol=>manifest.errors.push({symbol,code:publicFailure(error),stage:'subscription'}));
      if(!subscribed.size)break;
    }
  }
  for(const symbol of symbols) {
    if(!subscribed.has(symbol))continue;
    const code='US.'+symbol;
    try {
      const data=await call('get-kline',['--rehab-type',String(config.rehab_type),'--kl-type','2','--req-num',String(Math.min(config.bars,1000)),'--security',code]);
      if(!Array.isArray(data.kl_list))throw Error('INVALID_RESPONSE');
      const observation={provider:'moomoo',kind:'daily_kline',symbol,checked_at:new Date().toISOString(),rehab_type:config.rehab_type,requested_bars:config.bars,data};
      const contents=JSON.stringify(observation);
      const path=join(dir,symbol+'.json');writeFileSync(path,contents,'utf8');
      manifest.files.push({symbol,path:path.slice(root.length+1).replaceAll('\\','/'),bars:data.kl_list.length,sha256:createHash('sha256').update(contents).digest('hex')});
      process.stdout.write(JSON.stringify({symbol,bars:data.kl_list.length,status:'saved'})+'\n');
    } catch(error) {
      manifest.errors.push({symbol,code:publicFailure(error)});
      if(!manifest.files.length)break; // Fail fast when the desktop service is offline.
    }
  }
} catch(error) {manifest.errors.push({code:publicFailure(error)});}
mkdirSync(join(root,'data'),{recursive:true});
writeFileSync(join(root,'data','manifest.json'),JSON.stringify(manifest,null,2),'utf8');
process.stdout.write(JSON.stringify({saved:manifest.files.length,errors:manifest.errors,manifest:'data/manifest.json'})+'\n');
if(!manifest.files.length)process.exitCode=2;

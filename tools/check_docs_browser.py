import asyncio,json,base64,hashlib,argparse
from pathlib import Path
import websockets
parser=argparse.ArgumentParser(description='Optional read-only Firefox BiDi documentation UI gate; never accesses hardware.')
parser.add_argument('--websocket',default='ws://127.0.0.1:9239/session')
parser.add_argument('--base-url',default='http://127.0.0.1:8769/sparklink/')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if not args.base_url.startswith(('http://127.0.0.1:', 'http://localhost:')) or not args.websocket.startswith(('ws://127.0.0.1:', 'ws://localhost:')):
 parser.error('UI gate requires local preview and local independent Firefox')
OUT=args.output
OUT.mkdir(parents=True,exist_ok=False)
async def main():
 async with websockets.connect(args.websocket,open_timeout=10) as w:
  seq=0
  async def call(method,params):
   nonlocal seq
   seq+=1;await w.send(json.dumps({'id':seq,'method':method,'params':params}))
   while True:
    x=json.loads(await asyncio.wait_for(w.recv(),25))
    if x.get('id')==seq:
     if x.get('type')=='error':raise RuntimeError(x)
     return x['result']
  await call('session.new',{'capabilities':{}})
  context=(await call('browsingContext.create',{'type':'tab'}))['context']
  async def js(expression):
   value=await call('script.evaluate',{'expression':expression,'target':{'context':context},'awaitPromise':True})
   if value['type']!='success':raise RuntimeError(value)
   return value['result'].get('value')
  async def nav(path):await call('browsingContext.navigate',{'context':context,'url':args.base_url.rstrip('/')+'/'+path,'wait':'complete'})
  async def shot(name):
   await asyncio.sleep(.5)  # Capture after layout/paint, not only DOM insertion.
   b=await call('browsingContext.captureScreenshot',{'context':context});p=OUT/(name+'.png');p.write_bytes(base64.b64decode(b['data']));return {'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  result={'scope':'Firefox headless actual HTTP /sparklink/ navigation, JS search, DOM and screenshots; not hardware qualification','screenshots':[]}
  await call('browsingContext.setViewport',{'context':context,'viewport':{'width':1280,'height':900},'devicePixelRatio':1})
  await nav('index.html')
  result['document_title']=await js('document.title')
  result['home_tasks']=await js("['tutorials/index.html','how-to/index.html','reference/index.html','explanation/index.html','CURRENT_CAPABILITIES.html'].every(p=>Array.from(document.links).some(a=>a.href.endsWith(p)))")
  result['screenshots'].append(await shot('desktop-home'))
  await js("Array.from(document.links).find(a=>a.href.endsWith('reference/controller-events.html')).click();true")
  await asyncio.sleep(.5)
  result['navigation']=await js("location.pathname.endsWith('/reference/controller-events.html') && document.body.innerText.includes('GetControllerEventPosition')")
  result['table']=await js("document.querySelectorAll('table').length>=2")
  result['screenshots'].append(await shot('reference-table'))
  await nav('tutorials/build-documentation.html');result['code_block']=await js("Array.from(document.querySelectorAll('pre')).some(p=>p.textContent.includes('uv sync --locked --only-group docs'))")
  result['screenshots'].append(await shot('tutorial-code'))
  await nav('search.html?q=ControllerEventGet')
  found=False
  for _ in range(20):
   found=await js("Array.from(document.querySelectorAll('#search-results a')).some(a=>a.href.includes('controller-events.html'))")
   if found:break
   await asyncio.sleep(.5)
  result['javascript_search']=found
  result['screenshots'].append(await shot('search-results'))
  await nav('search.html?q=%E6%96%87%E6%A1%A3')
  chinese=False
  for _ in range(20):
   chinese=await js("document.querySelectorAll('#search-results a').length>0")
   if chinese:break
   await asyncio.sleep(.5)
  result['chinese_search']=chinese
  result['screenshots'].append(await shot('chinese-search-results'))
  await call('browsingContext.setViewport',{'context':context,'viewport':{'width':390,'height':844},'devicePixelRatio':1})
  await nav('index.html');result['mobile_no_page_overflow']=await js('document.documentElement.scrollWidth <= window.innerWidth')
  result['screenshots'].append(await shot('mobile-home'))
  await nav('reference/controller-events.html');result['mobile_table_container']=await js("Array.from(document.querySelectorAll('table')).every(t=>{let p=t.parentElement;return t.scrollWidth<=window.innerWidth || ['auto','scroll'].includes(getComputedStyle(p).overflowX)})")
  result['screenshots'].append(await shot('mobile-reference'))
  await call('browsingContext.setViewport',{'context':context,'viewport':{'width':1280,'height':900},'devicePixelRatio':1})
  await nav('ARCHITECTURE.html'); diagrams=False
  for _ in range(20):
   diagrams=await js("Array.from(document.querySelectorAll('.mermaid')).some(m=>{const s=m.querySelector('svg');return s && s.getBoundingClientRect().width>0 && s.getBoundingClientRect().height>0 && s.textContent.length>0})")
   if diagrams:break
   await asyncio.sleep(.5)
  await asyncio.sleep(1)
  result['mermaid_rendered']=diagrams
  result['screenshots'].append(await shot('architecture-diagram'))
  result['browser']=(await call('session.status',{}));result['status']='PASS' if all(result[k] is True for k in ['home_tasks','navigation','table','code_block','javascript_search','chinese_search','mobile_no_page_overflow','mobile_table_container','mermaid_rendered']) else 'PARTIAL'
  (OUT/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['screenshots','browser']},indent=2))
  await call('session.end',{})
  if result['status']!='PASS':raise SystemExit(1)
asyncio.run(main())

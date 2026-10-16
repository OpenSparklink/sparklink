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
  async def click(selector):
   await js("(()=>{const e=document.querySelector("+json.dumps(selector)+");if(!e)throw new Error('missing click target');e.scrollIntoView({block:'center'});return true})()")
   await asyncio.sleep(.2)
   coordinates=json.loads(await js("(()=>{const e=document.querySelector("+json.dumps(selector)+");if(!e)throw new Error('missing click target');const r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)throw new Error('hidden click target');const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(!hit||!e.contains(hit))throw new Error('obscured click target');return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)})})()"))
   await call('input.performActions',{'context':context,'actions':[{'type':'pointer','id':'docs-pointer','parameters':{'pointerType':'mouse'},'actions':[{'type':'pointerMove','origin':'viewport',**coordinates},{'type':'pointerDown','button':0},{'type':'pointerUp','button':0}]}]})
  async def nav(path):await call('browsingContext.navigate',{'context':context,'url':args.base_url.rstrip('/')+'/'+path,'wait':'complete'})
  async def shot(name):
   await asyncio.sleep(.5)  # Capture after layout/paint, not only DOM insertion.
   b=await call('browsingContext.captureScreenshot',{'context':context});p=OUT/(name+'.png');p.write_bytes(base64.b64decode(b['data']));return {'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  result={'scope':'Firefox headless actual HTTP /sparklink/ navigation, JS search, DOM and screenshots; not hardware qualification','screenshots':[]}
  await call('browsingContext.setViewport',{'context':context,'viewport':{'width':1280,'height':900},'devicePixelRatio':1})
  await nav('index.html')
  result['document_title']=await js('document.title')
  result['home_tasks']=await js("['tutorials/index.html','how-to/index.html','reference/index.html','explanation/index.html'].every(p=>Array.from(document.links).some(a=>a.href.endsWith(p)))")
  result['task_cards_desktop']=await js("document.querySelectorAll('.sl-task-card a').length===4 && getComputedStyle(document.querySelector('.sl-task-grid')).gridTemplateColumns.split(' ').length===2 && Array.from(document.querySelectorAll('.sl-task-card')).every(e=>parseFloat(getComputedStyle(e).paddingLeft)>=16)")
  result['versioned_brand']=await js("(async()=>{const stamp=await (await fetch(new URL('documentation-build.json',location.href))).json();return new URL(document.querySelector('.sl-brand-home').href).pathname===location.pathname && document.querySelector('.sl-version').href==='https://github.com/OpenSparklink/sparklink/tree/'+stamp.source_revision && document.querySelector('.sl-brand-caption').textContent.includes('Linux')})()")
  result['screenshots'].append(await shot('desktop-home'))
  await js("Array.from(document.links).find(a=>a.href.endsWith('reference/controller-events.html')).click();true")
  await asyncio.sleep(.5)
  result['navigation']=await js("location.pathname.endsWith('/reference/controller-events.html') && document.body.innerText.includes('GetControllerEventPosition')")
  result['chapter_breadcrumbs']=await js("document.querySelector('.sl-breadcrumbs [aria-current=page]').textContent.includes('Controller') && new URL(document.querySelector('.sl-breadcrumbs li:nth-child(2) a').href).pathname.endsWith('/reference/index.html') && document.querySelector('.sl-breadcrumbs').getBoundingClientRect().right<=innerWidth")
  await click('.sl-breadcrumbs li:nth-child(2) a')
  await asyncio.sleep(.3)
  result['breadcrumb_return']=await js("location.pathname.endsWith('/reference/index.html') && document.querySelector('.bd-article h1').textContent.includes('技术参考')")
  await nav('reference/controller-events.html')
  result['table']=await js("document.querySelectorAll('table').length>=2")
  result['table_column_legibility']=await js("Array.from(document.querySelectorAll('table tr')).every(r=>Array.from(r.cells).every(c=>c.getBoundingClientRect().width>=96))")
  result['book_sidebars']=await js("document.querySelector('.bd-sidebar-primary').getBoundingClientRect().width>0 && document.querySelector('.bd-sidebar-secondary').getBoundingClientRect().width>0 && document.body.innerText.includes('本页内容') && document.querySelectorAll('.primary-toggle').length===1 && document.querySelectorAll('.secondary-toggle').length===1")
  await click('.theme-switch-button')
  await click('.theme-change-button[data-mode="dark"]')
  await asyncio.sleep(.2)
  result['dark_mode']=await js("document.documentElement.dataset.theme==='dark'")
  await click('.bd-article h1')
  result['screenshots'].append(await shot('book-dark-reference'))
  await click('.theme-switch-button')
  await click('.theme-change-button[data-mode="light"]')
  await click('.bd-article h1')

  result['screenshots'].append(await shot('reference-table'))
  await nav('how-to/build-documentation.html');result['code_block']=await js("Array.from(document.querySelectorAll('pre')).some(p=>p.textContent.includes('uv sync --locked --only-group docs'))")
  await asyncio.sleep(.3)
  expected_copy=await js("(()=>{const b=document.querySelector('button.copybtn');return document.querySelector(b.dataset.clipboardTarget).textContent.replace(/\\n$/, '')})()")
  await click('button.copybtn')
  await asyncio.sleep(.1)
  copy_success=await js("document.querySelector('button.copybtn').classList.contains('success')")
  await js("(()=>{const t=document.createElement('textarea');t.id='docs-test-paste';t.style.position='fixed';t.style.top='4px';document.body.append(t);t.focus();return true})()")
  await call('input.performActions',{'context':context,'actions':[{'type':'key','id':'docs-keyboard','actions':[{'type':'keyDown','value':'\ue009'},{'type':'keyDown','value':'v'},{'type':'keyUp','value':'v'},{'type':'keyUp','value':'\ue009'}]}]})
  pasted=await js("document.getElementById('docs-test-paste').value")
  result['code_copy_paste']=copy_success and pasted==expected_copy and bool(pasted)
  await js("document.getElementById('docs-test-paste').remove();true")
  result['screenshots'].append(await shot('tutorial-code'))
  await nav('tutorials/index.html')
  await js("Array.from(document.links).find(a=>a.href.endsWith('tutorials/first-ws73-message.html')).click();true")
  await asyncio.sleep(.5)
  result['product_tutorial_navigation']=await js("location.pathname.endsWith('/tutorials/first-ws73-message.html') && document.body.innerText.includes('slktest') && document.body.innerText.includes('冻结') && document.body.innerText.includes('受限教程草案')")
  result['screenshots'].append(await shot('product-tutorial'))
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
  result['task_cards_mobile']=await js("getComputedStyle(document.querySelector('.sl-task-grid')).gridTemplateColumns.split(' ').length===1 && Array.from(document.querySelectorAll('.sl-task-card')).every(e=>e.getBoundingClientRect().right<=innerWidth)")
  result['screenshots'].append(await shot('mobile-home'))
  await click('.primary-toggle')
  result['mobile_navigation']=await js("document.getElementById('pst-primary-sidebar-modal').open && document.querySelector('.bd-sidebar-primary a[href$=\"reference/index.html\"]')!==null")
  result['screenshots'].append(await shot('book-mobile-navigation'))
  await nav('index.html')

  await nav('reference/controller-events.html');result['mobile_table_container']=await js("Array.from(document.querySelectorAll('table')).every(t=>{let p=t.parentElement;return t.scrollWidth<=window.innerWidth || ['auto','scroll'].includes(getComputedStyle(p).overflowX)})")
  result['mobile_breadcrumbs']=await js("document.documentElement.scrollWidth<=innerWidth && getComputedStyle(document.querySelector('.sl-breadcrumbs [aria-current=page]')).display==='none' && document.querySelector('.sl-breadcrumbs li:nth-child(2) a').getBoundingClientRect().width>0")
  result['screenshots'].append(await shot('mobile-reference'))
  await call('browsingContext.setViewport',{'context':context,'viewport':{'width':1280,'height':900},'devicePixelRatio':1})
  await nav('explanation/architecture.html'); diagrams=False
  for _ in range(20):
   diagrams=await js("Array.from(document.querySelectorAll('.mermaid')).some(m=>{const s=m.querySelector('svg');return s && s.getBoundingClientRect().width>0 && s.getBoundingClientRect().height>0 && s.textContent.length>0})")
   if diagrams:break
   await asyncio.sleep(.5)
  await asyncio.sleep(1)
  result['mermaid_rendered']=diagrams
  result['screenshots'].append(await shot('architecture-diagram'))
  await nav('how-to/index.html')
  await js("Array.from(document.links).find(a=>a.href.endsWith('how-to/check-business-roundtrip.html')).click();true")
  await asyncio.sleep(.5)
  result['business_evidence_navigation']=await js("location.pathname.endsWith('/how-to/check-business-roundtrip.html') && document.body.innerText.includes('NativeChannelRoundTrip') && document.body.innerText.includes('失败处理')")
  result['screenshots'].append(await shot('business-evidence-task'))
  await nav('explanation/qualification-boundaries.html')
  result['qualification_explanation']=await js("document.body.innerText.includes('NOCP') && Array.from(document.links).some(a=>a.href.startsWith('https://github.com/OpenSparklink/sparklink/blob/') && a.href.endsWith('/project/current-capabilities.md'))")
  result['screenshots'].append(await shot('qualification-explanation'))
  await nav('index.html')
  result['source_only_pages_excluded']=await js("(async()=>{for(const p of ['project/index.html','project/current-capabilities.html','history/index.html','decisions/index.html','evidence/index.html','CURRENT_CAPABILITIES.html']){if((await fetch(new URL(p,location.href))).status!==404)return false}return true})()")
  result['screenshots'].append(await shot('four-category-home'))
  redirects={}
  for old,new in {'tutorials/build-documentation.html':'how-to/build-documentation.html','tutorials/read-real-ws73-result.html':'how-to/check-business-roundtrip.html','how-to/prepare-vm-gate.html':'reference/vm-gate-inputs.html'}.items():
   await nav(old)
   for _ in range(10):
    ok=await js('location.pathname.endsWith('+json.dumps('/'+new)+')')
    if ok:break
    await asyncio.sleep(.2)
   redirects[old]=ok
  result['legacy_html_redirects']=all(redirects.values())
  result['redirect_targets']=redirects
  result['browser']=(await call('session.status',{}));result['status']='PASS' if all(result[k] is True for k in ['home_tasks','task_cards_desktop','task_cards_mobile','versioned_brand','navigation','chapter_breadcrumbs','breadcrumb_return','mobile_breadcrumbs','table','table_column_legibility','book_sidebars','dark_mode','code_copy_paste','mobile_navigation','code_block','product_tutorial_navigation','javascript_search','chinese_search','mobile_no_page_overflow','mobile_table_container','mermaid_rendered','business_evidence_navigation','qualification_explanation','source_only_pages_excluded','legacy_html_redirects']) else 'PARTIAL'
  (OUT/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['screenshots','browser']},indent=2))
  await call('session.end',{})
  if result['status']!='PASS':raise SystemExit(1)
asyncio.run(main())

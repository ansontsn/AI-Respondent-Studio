from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .models import QuestionType, now, uid
from .storage import dump
from .validator import visible, value_errors

logger = logging.getLogger(__name__)

HTML = r'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>授權本地測試表單</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fb;color:#182339;font:16px 'Microsoft JhengHei',sans-serif}main{max-width:880px;margin:40px auto;padding:32px;background:white;border-radius:16px;box-shadow:0 8px 32px #12213c10}h1{font-size:26px}.muted{color:#64748b}.q-field{padding:22px 0;border-bottom:1px solid #e4e9f2}label{display:block;margin:10px 0}input[type=text],textarea,select{width:100%;padding:12px;border:1px solid #c6d0df;border-radius:8px;font:inherit}button{padding:12px 24px;margin:20px 12px 0 0;border:0;border-radius:8px;background:#3159d9;color:white;font:inherit;cursor:pointer}.grid-row{padding:12px;background:#f6f8fc;margin:8px 0}.grid-row label{display:inline-block;margin-right:18px}.error{color:#b42318}#success{background:#ecfdf3;padding:24px}pre{white-space:pre-wrap;font:inherit}
</style></head><body><main><p class="muted">AI 問卷自動填寫 · 本地測試工作區</p><h1 id="title"></h1><p id="description"></p><div id="content"></div><p id="error" class="error" role="alert"></p></main>
<script>
const survey=__SCHEMA__;let current=survey.pages[0].id,answers={},visited=[],review=false;window.testToken=crypto.randomUUID();
const root=document.getElementById('content');document.getElementById('title').textContent=survey.title;document.getElementById('description').textContent=survey.description;
function node(tag,text,attrs={}){let e=document.createElement(tag);if(text!==null)e.textContent=text;for(let[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e}
function matches(c){if(!(c.question_id in answers))return false;let a=answers[c.question_id],b=c.value;switch(c.operator){case'eq':return JSON.stringify(a)===JSON.stringify(b);case'ne':return JSON.stringify(a)!==JSON.stringify(b);case'includes':return Array.isArray(a)||typeof a==='string'?a.includes(b):false;case'gt':return Number(a)>Number(b);case'gte':return Number(a)>=Number(b);case'lt':return Number(a)<Number(b);case'lte':return Number(a)<=Number(b)}}
function isVisible(q){return(q.display_if||[]).every(matches)}
function options(q,container,name,type,row=null){for(let o of q.options){let l=node('label',null),i=node('input',null,{type,name,value:o.id,'data-opt':o.id});if(row)i.dataset.row=row;l.append(i,document.createTextNode(' '+o.label));container.append(l)}}
function read(q,box){if(q.type==='short_text'||q.type==='paragraph')return box.querySelector('input,textarea').value;if(q.type==='dropdown'){return box.querySelector('select').value||null}if(q.type==='linear_scale'||q.type==='likert'){let i=box.querySelector('input:checked');return i?Number(i.value):null}if(q.type==='single_grid'||q.type==='checkbox_grid'){let v={};for(let r of q.rows){let items=[...box.querySelectorAll('input')].filter(i=>i.dataset.row===r.id&&i.checked);v[r.id]=q.type==='single_grid'?(items[0]?.value||null):items.map(i=>i.value)}return v}let checked=[...box.querySelectorAll('input:checked')];return q.type==='multiple'?checked.map(i=>i.value):checked[0]?.value||null}
function collect(){let p=survey.pages.find(p=>p.id===current);for(let q of p.questions){let box=[...root.querySelectorAll('[data-qid]')].find(b=>b.dataset.qid===q.id);if(isVisible(q)){answers[q.id]=read(q,box)}else{delete answers[q.id]}}}
function refresh(){collect();let p=survey.pages.find(p=>p.id===current);for(let q of p.questions){let box=[...root.querySelectorAll('[data-qid]')].find(b=>b.dataset.qid===q.id);box.hidden=!isVisible(q)}}
function render(){root.replaceChildren();let p=survey.pages.find(p=>p.id===current);root.append(node('h2',p.title));let form=node('form',null,{id:'test-form'});form.onsubmit=e=>{e.preventDefault();next()};for(let q of p.questions){let b=node('section',null,{'data-qid':q.id,class:'q-field'});b.append(node('h3',q.title+(q.required?' *':'')));if(q.type==='short_text'||q.type==='paragraph')b.append(node(q.type==='paragraph'?'textarea':'input',null,q.type==='paragraph'?{maxlength:q.max_length}:{type:'text',maxlength:q.max_length}));else if(q.type==='dropdown'){let s=node('select',null);s.append(node('option','請選擇',{value:''}));for(let o of q.options)s.append(node('option',o.label,{value:o.id}));b.append(s)}else if(q.type==='linear_scale'||q.type==='likert'){let sq={options:[]};for(let n=q.scale_min;n<=q.scale_max;n++)sq.options.push({id:String(n),label:String(n)});options(sq,b,q.id,'radio')}else if(q.type==='single_grid'||q.type==='checkbox_grid'){for(let r of q.rows){let row=node('div',null,{'data-rowid':r.id,class:'grid-row'});row.append(node('strong',r.label));options(q,row,q.id+'_'+r.id,q.type==='single_grid'?'radio':'checkbox',r.id);b.append(row)}}else if(q.type==='single'||q.type==='multiple')options(q,b,q.id,q.type==='single'?'radio':'checkbox');else b.append(node('p','此題型不支援，請修正問卷。'));b.onchange=refresh;form.append(b)}let nextButton=node('button','下一頁',{type:'submit',id:'next'});form.append(nextButton);root.append(form);refresh()}
function valid(){let p=survey.pages.find(p=>p.id===current);for(let q of p.questions){if(!isVisible(q))continue;let v=answers[q.id],empty=v===null||v===''||(Array.isArray(v)&&!v.length);if(q.required&&empty)return q.title+' 尚未填寫';if(q.type.includes('grid')&&q.required&&q.rows.some(r=>v[r.id]===null||v[r.id]?.length===0))return q.title+' 有未填列';if(q.type==='multiple'&&Array.isArray(v)&&((q.min_choices&&v.length<q.min_choices)||(q.max_choices&&v.length>q.max_choices)))return q.title+' 選取數不符合限制'}return''}
function next(){collect();let error=valid();document.getElementById('error').textContent=error;if(error)return;let p=survey.pages.find(p=>p.id===current);visited.push(current);let route=p.routes.find(r=>matches(r.when));let index=survey.pages.indexOf(p);let target=route?.target||p.default_next||survey.pages[index+1]?.id||'END';if(target==='END'){review=true;root.replaceChildren(node('h2','填寫結果預覽'),node('pre',JSON.stringify(answers,null,2)));let s=node('button','提交',{id:'submit',type:'button'});s.onclick=submit;root.append(s)}else{current=target;render()}}
async function submit(){let button=document.getElementById('submit');button.disabled=true;try{let response=await fetch('/submit/'+encodeURIComponent(survey.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:window.testToken,answers,visited})});let data=await response.json();if(!response.ok)throw Error(data.error||'提交失敗');root.replaceChildren(node('section','提交成功 · 收件編號 '+data.receipt,{id:'success','data-receipt':data.receipt}));document.getElementById('error').textContent=''}catch(e){document.getElementById('error').textContent=e.message;button.disabled=false}}
render();
</script></body></html>'''


class MockFormServer:
    def __init__(self, db, port: int = 8765):
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS local_receipts (id TEXT PRIMARY KEY,questionnaire_id TEXT NOT NULL,token TEXT NOT NULL,answers TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(questionnaire_id,token))")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                logger.debug("Local form: %s", format % args)

            def send(self, status, content, content_type="application/json; charset=utf-8"):
                body = content.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/health":
                    return self.send(200, dump({"ok": True, "workspace_id": owner.db.metadata()["id"]}))
                prefix = "/schema/" if path.startswith("/schema/") else "/form/"
                if not path.startswith(prefix):
                    return self.send(404, dump({"error": "不存在的測試頁面"}))
                q = owner.db.get("questionnaire", path[len(prefix):])
                if not q or q.purpose != "test" or not q.confirmed:
                    return self.send(404, dump({"error": "未找到已確認的測試問卷"}))
                data = dump(q).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
                return self.send(200, data if prefix == "/schema/" else HTML.replace("__SCHEMA__", data),
                                 "application/json; charset=utf-8" if prefix == "/schema/" else "text/html; charset=utf-8")

            def do_POST(self):
                path = urlsplit(self.path).path
                if not path.startswith("/submit/"):
                    return self.send(404, dump({"error": "不存在的提交路徑"}))
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length <= 0 or length > 1_000_000:
                        raise ValueError("提交大小不合法")
                    data = json.loads(self.rfile.read(length))
                    q = owner.db.get("questionnaire", path[len("/submit/"):])
                    if not q or q.purpose != "test" or not q.confirmed:
                        raise ValueError("問卷不允許測試提交")
                    values, expected, visited = {}, [], []
                    current = q.pages[0].id
                    if not isinstance(data.get("answers"), dict) or not isinstance(data.get("token"), str) or not 1 <= len(data["token"]) <= 100:
                        raise ValueError("提交格式不合法")
                    while current != "END":
                        p = next(p for p in q.pages if p.id == current)
                        visited.append(current)
                        for item in p.questions:
                            if not visible(item, values):
                                continue
                            expected.append(item.id)
                            value = data["answers"].get(item.id)
                            errors = value_errors(item, value)
                            if errors:
                                raise ValueError(f"{item.id}: {'；'.join(errors)}")
                            if value is not None:
                                values[item.id] = value
                        current = q.next_page(current, values)
                    if set(data["answers"]) - set(expected) or data.get("visited") != visited:
                        raise ValueError("提交包含分流外的題目或頁面路徑不符")
                    with owner.db.connect() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        receipt = conn.execute("SELECT id FROM local_receipts WHERE questionnaire_id=? AND token=?", (q.id, data["token"])).fetchone()
                        id = receipt["id"] if receipt else uid()
                        if not receipt:
                            conn.execute("INSERT INTO local_receipts VALUES(?,?,?,?,?)", (id, q.id, data["token"], dump(values), now()))
                    self.send(200, dump({"ok": True, "receipt": id}))
                except Exception as exc:
                    logger.exception("Local form submission rejected")
                    self.send(400, dump({"error": str(exc) if isinstance(exc, ValueError) else "本地表單儲存失敗"}))

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="local-test-form")

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def url(self, questionnaire_id):
        return f"http://127.0.0.1:{self.port}/form/{questionnaire_id}"

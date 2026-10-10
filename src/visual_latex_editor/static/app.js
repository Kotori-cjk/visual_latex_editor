'use strict';
const $ = id => document.getElementById(id);
const labels = {title:'文档标题',heading:'标题',text:'文字',math:'公式',table:'表格',figure:'图片',latex:'LaTeX'};
const icons = {title:'T',heading:'H',text:'¶',math:'ƒ',table:'▦',figure:'▧',latex:'{}'};
let state, selected, mode='visual', filter='all', dirty=false, upload=null, zoom=1;
let history=[], polling=null, toastTimer, compiledSignature='', inserting=false;
const esc = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message,error=false){$('toast').textContent=message;$('toast').style.background=error?'#a6543b':'#284c3d';$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
async function api(path,data){
  const options = data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Editor-Token':state.token},body:JSON.stringify({revision:state.revision,...data})};
  const response=await fetch(path,options);const body=await response.json();
  if(!response.ok)throw new Error(body.error||'请求失败');return body;
}
function drawOutline(){
  const query=$('search').value.toLowerCase();
  const blocks=state.blocks.filter(b=>(filter==='all'||b.kind===filter||(filter==='heading'&&b.kind==='title'))&&(!query||(b.label+b.source).toLowerCase().includes(query)));
  $('block-count').textContent=state.blocks.length+' 块';
  $('outline').innerHTML=blocks.map(b=>`<button class="outline-item ${b.kind} ${selected?.id===b.id?'active':''}" data-id="${b.id}" title="${esc(b.label)}"><span class="type-icon">${icons[b.kind]}</span><span class="item-title">${esc(b.label||labels[b.kind])}</span></button>`).join('');
  $('outline').querySelectorAll('button').forEach(button=>button.onclick=()=>selectBlock(button.dataset.id,true));
}
function setZoom(){
  const width=Math.max(270,$('preview-scroll').clientWidth-70)*zoom;
  $('pages').style.setProperty('--page-width',width+'px');$('zoom-label').textContent=Math.round(zoom*100)+'%';
}
function drawPages(){
  const signature=state.build_id;
  if(signature===compiledSignature)return;
  compiledSignature=signature;
  if(!state.pages.length){$('pages').innerHTML='<div class="empty-preview"><h2>新文档已就绪</h2><p>插入内容开始写作，或编译查看 PDF。</p></div>';return;}
  const scroll=$('preview-scroll').scrollTop;
  $('pages').innerHTML=state.pages.map(p=>`<article class="pdf-page" data-page="${p.number}" style="aspect-ratio:${p.width}/${p.height}"><span class="page-number">${p.number}</span><img src="${p.image}" alt="报告第 ${p.number} 页">${p.regions.map(r=>{
    const b=state.blocks.find(b=>b.id===r.block_id);return `<button class="hit ${b?.kind||''}" data-id="${r.block_id}" aria-label="编辑${labels[b?.kind]||'内容'}：${esc((b?.label||'').slice(0,80))}" title="${esc((b?.label||'点击编辑').slice(0,90))}" style="left:${r.x*100}%;top:${r.y*100}%;width:${r.w*100}%;height:${r.h*100}%"></button>`;
  }).join('')}</article>`).join('');
  document.querySelectorAll('.hit').forEach(hit=>hit.onclick=()=>selectBlock(hit.dataset.id));
  setZoom();$('preview-scroll').scrollTop=scroll;highlight();
}
function highlight(){
  document.querySelectorAll('.hit').forEach(hit=>hit.classList.toggle('active',hit.dataset.id===selected?.id));
  const hit=document.querySelector('.hit.active');
  $('selected-location').textContent=hit?'第 '+hit.closest('.pdf-page').dataset.page+' 页':'';
}
function refreshControls(){
  $('save-status').textContent=dirty?'有未保存修改':'已保存 '+state.last_saved;
  $('undo').disabled=!history.length||state.busy;
  $('compile').disabled=state.busy||inserting;
  $('insert-block').disabled=inserting;
  $('new-document').disabled=state.busy;
  $('compile').innerHTML=state.busy?'正在编译…':'<span>▶</span> 编译 PDF';
  $('export-pdf').disabled=state.busy||state.preview_revision!==state.revision||!state.pages.length;
  $('page-count').textContent=state.pages.length?state.pages.length+' 页':'';
  $('notice').classList.toggle('error',!!state.error);
  const stale=state.preview_revision!==state.revision;
  $('notice').classList.toggle('stale',stale&&!state.busy&&!state.error);
  $('notice-text').textContent=state.busy?'正在编译并更新 PDF 预览…':state.error?'编译未通过，已保留上一次成功的 PDF。查看日志定位错误。':stale?'修改已保存，预览尚未更新。点击「编译 PDF」查看新版本。':'预览已更新 · 点击页面内容开始编辑';
  if(state.busy&&!polling)polling=setInterval(poll,1200);
  if(!state.busy&&polling){clearInterval(polling);polling=null;}
}
function receive(next){state=next;$('document-name').textContent=(state.blocks.find(b=>b.kind==='title')?.label||'LaTeX 文档')+' · 编辑副本';drawOutline();drawPages();refreshControls();}
async function poll(){try{receive(await api('/api/state'));}catch(e){toast(e.message,true);}}
function markDirty(){dirty=true;$('edit-status').textContent='有修改，尚未保存';$('apply').disabled=false;refreshControls();}
function leaveDirty(){return !dirty||confirm('当前内容有未保存修改，放弃这些修改并切换？');}
function selectBlock(id,scroll=false){
  if(selected?.id===id&&!scroll)return;
  if(!leaveDirty())return;
  selected=state.blocks.find(b=>b.id===id);if(!selected)return;
  dirty=false;upload=null;mode=['math','table','latex'].includes(selected.kind)?'latex':'visual';
  $('inspector-empty').hidden=true;$('editor').hidden=false;
  $('inspector-title').textContent=selected.kind==='figure'?'图片与图注':(selected.label||labels[selected.kind]);
  $('kind-badge').textContent=labels[selected.kind];$('block-source').value=selected.source;
  $('edit-status').textContent='第 '+selected.line_start+'–'+selected.line_end+' 行';$('apply').disabled=true;
  renderVisual();switchMode(mode);drawOutline();highlight();refreshControls();
  if(scroll){document.querySelector('.hit.active')?.scrollIntoView({behavior:'smooth',block:'center'});}
}
function renderVisual(){
  const panel=$('visual-panel');
  if(selected.kind==='figure'){
    const size=selected.options.match(/(width|height)\s*=\s*([\d.]+)\s*(\\linewidth|\\textwidth|cm|mm|in|pt)/);
    const axis=size?.[1]||'width',value=+(size?.[2]||1),unit=size?.[3]||'\\linewidth';
    const relative=['\\linewidth','\\textwidth'].includes(unit);
    panel.innerHTML=`<img id="image-preview" class="image-preview" src="/assets/${encodeURIComponent(selected.asset)}" alt="选中图片的预览"><button id="upload-button" class="upload-zone"><span>＋</span> 选择图片替换</button><input id="image-file" type="file" accept="image/png,image/jpeg,image/webp" hidden><p class="help" id="image-file-name">支持 PNG、JPG、WebP。保留图片比例。</p><label class="field-label">图片尺寸</label><div class="image-settings"><select id="size-type" aria-label="图片尺寸方式"><option value="relative">占正文宽度</option><option value="width">宽度（cm）</option><option value="height">高度（cm）</option></select><input id="size-value" type="number" step="0.1" min="0.1" aria-label="图片尺寸"><span class="unit" id="size-unit"></span></div><p class="help">替换图片后可调整大小，布局会由 LaTeX 自动重排。</p><label class="field-label" for="image-caption">图注</label><textarea id="image-caption" spellcheck="false">${esc(selected.caption)}</textarea><p class="help">图注支持普通文字和 LaTeX 公式。</p>`;
    $('size-type').value=relative?'relative':axis;
    $('size-value').value=relative?Math.round(value*1000)/10:unit==='mm'?value/10:unit==='in'?value*2.54:unit==='pt'?value*2.54/72.27:value;
    $('size-unit').textContent=relative?'%':'cm';
    $('upload-button').onclick=()=>$('image-file').click();
    $('image-file').onchange=async()=>{
      const file=$('image-file').files[0];if(!file)return;
      if(file.size>24*1024*1024){toast('图片需要小于 24 MB。',true);return;}
      const reader=new FileReader();reader.onload=()=>{upload=String(reader.result).split(',')[1];$('image-preview').src=reader.result;$('image-file-name').textContent=file.name+' · 替换后点击保存';markDirty();};reader.readAsDataURL(file);
    };
    $('size-type').onchange=()=>{const relative=$('size-type').value==='relative';$('size-unit').textContent=relative?'%':'cm';$('size-value').value=relative?88:6.2;markDirty();};
    $('size-value').oninput=markDirty;$('image-caption').oninput=markDirty;
  } else if(selected.runs){
    panel.innerHTML='<label class="field-label">文字内容</label><p class="help">直接修改下面的文字。浅绿色片段是公式；修改公式请切换到 LaTeX。</p>'+selected.runs.map((r,i)=>r.editable&&r.text.trim()?`<textarea class="prose-run" rows="1" data-run="${i}" aria-label="文字片段 ${i+1}">${esc(r.text)}</textarea>`:r.text.trim()?`<span class="protected-run ${r.text.startsWith('$')?'':'syntax'}">${esc(r.text)}</span>`:'').join('');
    panel.querySelectorAll('textarea').forEach(area=>{area.style.height='auto';area.style.height=Math.max(44,area.scrollHeight+3)+'px';area.oninput=()=>{area.style.height='auto';area.style.height=area.scrollHeight+3+'px';markDirty();};});
  } else {
    panel.innerHTML='<p class="help">此内容包含公式、表格或排版命令。请在 LaTeX 模式中修改，保存后重新编译。</p><button id="go-latex">编辑 LaTeX →</button>';$('go-latex').onclick=()=>switchMode('latex');
  }
}
function latexEscape(text){return text.replace(/[\\&%$#_{}~^]/g,c=>({'\\':'\\textbackslash{}','&':'\\&','%':'\\%','$':'\\$','#':'\\#','_':'\\_','{':'\\{','}':'\\}','~':'\\textasciitilde{}','^':'\\textasciicircum{}'}[c]));}
function argumentSpan(raw,command){
  const match=raw.match(new RegExp('\\\\'+command+'(?:\\[[^\\]]*\\])?\\s*\\{'));if(!match)return null;
  const start=match.index+match[0].length;let depth=1;
  for(let i=start;i<raw.length;i++){
    if(raw[i]==='\\'){i++;continue;}if(raw[i]==='{')depth++;if(raw[i]==='}'&&!--depth)return [start,i];
  }throw new Error('图注的花括号不匹配。');
}
function visualSource(){
  if(selected.kind==='figure'){
    let raw=$('block-source').value;
    const type=$('size-type').value,value=Number($('size-value').value);
    if(!Number.isFinite(value)||value<=0||type==='relative'&&value>100)throw new Error('请输入有效尺寸；正文宽度比例为 0–100%。');
    const option=type==='relative'?'width='+Number((value/100).toFixed(5))+'\\linewidth':type+'='+value+'cm';
    const match=raw.match(/\\includegraphics(?:\[([^\]]*)\])?\{/);if(!match)throw new Error('没有找到图片命令。');
    const others=(match[1]||'').split(',').filter(v=>v.trim()&&!/^\s*(width|height|scale|keepaspectratio)\b/.test(v));
    raw=raw.slice(0,match.index)+'\\includegraphics['+[option,...others].join(',')+']{'+raw.slice(match.index+match[0].length);
    const span=argumentSpan(raw,'caption');
    if(span)raw=raw.slice(0,span[0])+$('image-caption').value+raw.slice(span[1]);
    return raw;
  }
  if(!selected.runs)return $('block-source').value;
  return selected.runs.map((r,i)=>{
    const area=$('visual-panel').querySelector(`[data-run="${i}"]`);
    // Untouched source is preserved exactly, including escaped characters.
    return area&&area.value!==r.text?latexEscape(area.value):r.text;
  }).join('');
}
function currentSource(){return mode==='latex'?$('block-source').value:visualSource();}
function switchMode(next){
  if(next===mode&&$('latex-panel').hidden===(next!=='latex'))return;
  if(next==='latex'&&selected?.runs||next==='latex'&&selected?.kind==='figure'){
    try{$('block-source').value=visualSource();}catch(e){toast(e.message,true);return;}
  }
  if(next==='visual'&&mode==='latex'&&dirty){
    toast('LaTeX 修改请先保存，再切换到可视化编辑。');return;
  }
  mode=next;$('visual-panel').hidden=next!=='visual';$('latex-panel').hidden=next!=='latex';
  $('visual-tab').classList.toggle('active',next==='visual');$('latex-tab').classList.toggle('active',next==='latex');
  if(next==='visual')$('visual-panel').querySelectorAll('textarea.prose-run').forEach(area=>{area.style.height='auto';area.style.height=Math.max(44,area.scrollHeight+3)+'px';});
}
async function apply(){
  if(!selected||!dirty)return true;
  const id=selected.id,before=state.source;
  try{
    const next=await api('/api/block',{id,source:currentSource(),image:upload});
    if(next.source!==before){history.push(before);if(history.length>25)history.shift();}
    dirty=false;receive(next);selected=null;selectBlock(id);toast('已保存到编辑副本。编译后更新 PDF。');return true;
  }catch(e){toast(e.message,true);return false;}
}
async function compile(){
  if(dirty&&!await apply())return;
  try{receive(await api('/api/compile',{}));}catch(e){toast(e.message,true);}
}
async function undo(){
  if(!history.length||!leaveDirty())return;
  try{const next=await api('/api/save',{source:history[history.length-1]});history.pop();dirty=false;const id=selected?.id;receive(next);selected=null;if(id)selectBlock(id);toast('已撤销最近一次保存。编译后查看结果。');}catch(e){toast(e.message,true);}
}
async function download(kind){
  if(dirty&&!await apply())return;
  if(kind==='pdf'&&state.preview_revision!==state.revision){toast('先编译最新修改，再下载 PDF。');return;}
  try{const response=await fetch('/api/export/'+kind);if(!response.ok){const data=await response.json();throw new Error(data.error);}const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='visual_latex_document.'+kind;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message,true);}
}
$('visual-tab').onclick=()=>switchMode('visual');$('latex-tab').onclick=()=>switchMode('latex');
$('block-source').oninput=markDirty;$('apply').onclick=apply;$('compile').onclick=compile;$('undo').onclick=undo;
$('search').oninput=drawOutline;
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));drawOutline();});
$('zoom-in').onclick=()=>{zoom=Math.min(2,zoom+.1);setZoom();};$('zoom-out').onclick=()=>{zoom=Math.max(.5,zoom-.1);setZoom();};$('fit').onclick=()=>{zoom=1;setZoom();};
$('regions-toggle').onclick=()=>{$('pages').classList.toggle('show-regions');$('regions-toggle').classList.toggle('active');};
$('export-tex').onclick=()=>download('tex');$('export-pdf').onclick=()=>download('pdf');
$('log-toggle').onclick=()=>{$('log-content').textContent=state.log||'编译服务正在启动…';$('log-dialog').showModal();};$('log-close').onclick=()=>$('log-dialog').close();
$('source-toggle').onclick=()=>{if(!leaveDirty())return;$('full-source').value=state.source;$('source-path').textContent=state.project;$('source-dialog').showModal();};
$('source-close').onclick=()=>$('source-dialog').close();
$('source-save').onclick=async()=>{try{const before=state.source;const next=await api('/api/save',{source:$('full-source').value});if(next.source!==before)history.push(before);dirty=false;receive(next);selected=null;$('editor').hidden=true;$('inspector-empty').hidden=false;$('source-dialog').close();toast('源文件已保存。');}catch(e){toast(e.message,true);}};
$('import').onclick=()=>{if(leaveDirty())$('import-file').click();};
$('import-file').onchange=async()=>{const file=$('import-file').files[0];if(!file)return;try{const before=state.source;const next=await api('/api/import',{source:await file.text()});history.push(before);dirty=false;selected=null;receive(next);$('editor').hidden=true;$('inspector-empty').hidden=false;toast('已导入文档，正在生成预览。');await compile();}catch(e){toast(e.message,true);}finally{$('import-file').value='';}};
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if($('source-dialog').open)$('source-save').click();else apply();}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('resize',setZoom);
api('/api/state').then(receive).catch(e=>{$('notice-text').textContent='服务连接失败：'+e.message;toast(e.message,true);});

function pageFields(){
  for(const area of ['header','footer'])$(area+'-fields').hidden=$(area+'-mode').value!=='custom';
}
$('page-settings').onclick=async()=>{
  if(dirty&&!await apply())return;
  const settings=state.page_settings;
  for(const area of ['header','footer']){
    $(area+'-mode').value=settings[area];
    for(const slot of ['left','center','right'])$(area+'-'+slot).value=settings[area+'_'+slot];
  }
  pageFields();$('page-dialog').showModal();
};
$('header-mode').onchange=pageFields;$('footer-mode').onchange=pageFields;
$('page-close').onclick=()=>$('page-dialog').close();
$('page-save').onclick=async()=>{
  const settings={};
  for(const area of ['header','footer']){
    settings[area]=$(area+'-mode').value;
    for(const slot of ['left','center','right'])settings[area+'_'+slot]=$(area+'-'+slot).value;
  }
  try{
    const before=state.source,next=await api('/api/page-settings',{settings});
    if(next.source!==before){history.push(before);if(history.length>25)history.shift();}
    receive(next);selected=null;$('editor').hidden=true;$('inspector-empty').hidden=false;
    $('page-dialog').close();await compile();
  }catch(e){toast(e.message,true);}
};

$('new-document').onclick=()=>{if(leaveDirty())$('new-dialog').showModal();};
$('new-close').onclick=()=>$('new-dialog').close();
$('new-create').onclick=async()=>{
  try{
    const next=await api('/api/new',{title:$('new-title').value});
    dirty=false;selected=null;history=[];upload=null;
    receive(next);$('editor').hidden=true;$('inspector-empty').hidden=false;
    $('new-dialog').close();toast('已创建新文档，旧文档已归档。');await compile();
  }catch(e){toast(e.message,true);}
};
async function insertBlock(kind,image=null){
  if(inserting)return;
  if(dirty&&!await apply())return;
  inserting=true;refreshControls();
  const snippets={"text": "在这里输入新段落。", "heading": "\\section{新标题}", "math": "\\[\nE = mc^2\n\\]", "table": "\\begin{table}[H]\n\\centering\n\\begin{tabular}{ll}\n\\toprule\n项目 & 数值 \\\\\n\\midrule\n示例 & 1 \\\\\n\\bottomrule\n\\end{tabular}\n\\caption{表格说明}\n\\end{table}", "figure": "\\begin{figure}[H]\n\\centering\n\\includegraphics[width=0.7\\linewidth]{new-image.pdf}\n\\caption{图片说明}\n\\end{figure}"};
  try{
    const before=state.source;
    const position=selected?state.blocks.find(b=>b.id===selected.id)?.end:undefined;
    const bodyStart=before.indexOf('\\begin{document}')+'\\begin{document}'.length;
    const index=position!==undefined&&position>=bodyStart?position:before.lastIndexOf('\\end{document}');
    const source=before.slice(0,index)+'\n\n'+snippets[kind]+'\n\n'+before.slice(index);
    let next=await api('/api/save',{source});
    history.push(before);dirty=false;selected=null;receive(next);
    const block=next.blocks.find(b=>b.start>=index&&b.source.includes(kind==='figure'?'new-image.pdf':snippets[kind]));
    if(image&&block){next=await api('/api/block',{id:block.id,source:block.source,image});receive(next);}
    if(block)selectBlock(block.id,true);
    toast('已插入内容，可在右侧编辑。');
  }catch(e){toast(e.message,true);}finally{inserting=false;refreshControls();}
}
$('insert-block').onchange=()=>{
  const kind=$('insert-block').value;$('insert-block').value='';
  if(kind==='figure')$('insert-image').click();else if(kind)insertBlock(kind);
};
$('insert-image').onchange=()=>{
  const file=$('insert-image').files[0];if(!file)return;
  if(file.size>24*1024*1024){toast('图片需要小于 24 MB。',true);return;}
  const reader=new FileReader();reader.onload=()=>insertBlock('figure',String(reader.result).split(',')[1]);
  reader.readAsDataURL(file);$('insert-image').value='';
};

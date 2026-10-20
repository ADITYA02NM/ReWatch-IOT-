const $=(s)=>document.querySelector(s);
const BANDS=["GREEN","BLUE","YELLOW","RED","PURPLE"];
let paused=false,evonly=false,count=0,skew=0;
const stream=$("#stream");

function connect(){
  const url=(location.protocol==="https:"?"wss://":"ws://")+location.host+"/ws";
  const ws=new WebSocket(url);
  ws.onopen=()=>{$("#conn").textContent="live";$("#conn").className="ok";ping(ws);};
  ws.onclose=()=>{$("#conn").textContent="offline — retrying";$("#conn").className="err";setTimeout(connect,1500);};
  ws.onmessage=(e)=>{count++;let m;try{m=JSON.parse(e.data);}catch{return;}handle(m,ws);};
}
function ping(ws){if(ws.readyState!==1)return;ws.send(JSON.stringify({op:"ping",c:Date.now()}));setTimeout(()=>ping(ws),5000);}
function handle(m,ws){
  if(m.t==="pong"){skew=(m.s*1000)-Date.now();$("#v-skew").textContent=Math.round(skew)+" ms";return;}
  if(m.t==="hello"){if(m.version)$("#v-ver").textContent=m.version;$("#v-mqtt").textContent=m.mqtt?"connected":"down";$("#v-mqtt").className=m.mqtt?"ok":"err";if(m.state)risk(m.state);nodes(m.nodes);devs(m.telemetry,m.verify);return;}
  if(m.t==="mqtt"){$("#v-mqtt").textContent=m.ok?"connected":"down";$("#v-mqtt").className=m.ok?"ok":"err";return;}
  if(m.t==="bus"){
    if(m.topic==="rewatch/threat/state")risk(m.d);
    else if(m.topic.indexOf("/health/")>0)nodeOne(m.topic.split("/").pop(),m.d);
    else if(m.topic.indexOf("/telemetry")>0)devOne(m.topic.split("/")[2],m.d,null);
    else if(m.topic.indexOf("/verify/")>0)devOne(m.topic.split("/").pop(),null,m.d);
    if(!evonly)line(m.topic,m.d,false);
  }
  if(m.t==="event"){line("event:"+m.e.kind,m.e,true);}
}
function risk(s){
  $("#v-score").textContent=Math.round(s.score||0)+"/100";
  $("#v-band").textContent=s.band;$("#v-band").className="b-"+s.band;
  $("#v-reason").textContent=s.reason||"—";
  const i=s.incident;$("#v-inc").textContent=i?(i.id+" · "+i.state+(i.state==="open"?" · "+Math.ceil(i.remaining||0)+"s":"")):"none";
  const tb=$("#contrib").querySelector("tbody");
  tb.innerHTML=(s.contrib||[]).map((c)=>`<tr><td>${c.src||""}</td><td>${Math.round(c.points)}</td><td><span class="bar" style="width:${Math.min(c.points,100)*1.4}px"></span></td><td style="white-space:normal">${esc(c.title||"")}</td></tr>`).join("")||'<tr><td class="dim">— idle —</td></tr>';
}
const N={};
function nodes(o){for(const k in(o||{}))nodeOne(k,o[k]);}
function nodeOne(id,d){N[id]=Object.assign(N[id]||{},d,{rx:Date.now()/1000});render();}
function render(){
  const now=Date.now()/1000;
  $("#nodes").querySelector("tbody").innerHTML=Object.keys(N).sort().map((k)=>{
    const d=N[k],up=d.online&&(now-(d.rx||0)<20);
    return `<tr><td>${k}</td><td class="${up?"ok":"blue"}">${up?"up":"offline"}</td><td class="dim">${esc(d.role||"")}</td></tr>`;
  }).join("");
  let n=0;for(const k in N)if(N[k].online&&now-(N[k].rx||0)<20)n++;
  $("#v-wsc").textContent=(window.__wsc||"?");
}
const D={};
function devs(t,v){for(const k in(t||{}))devOne(k,t[k],null);for(const k in(v||{}))devOne(k,null,v[k]);}
function devOne(k,t,v){D[k]=D[k]||{};if(t)D[k].t=t;if(v)D[k].v=v;
  $("#devs").querySelector("tbody").innerHTML=Object.keys(D).sort().map((x)=>{
    const t=D[x].t||{},v=D[x].v||{};
    return `<tr><td>${esc(t.room||x)}</td><td>${t.temp_c!=null?t.temp_c+"°":"—"}</td><td class="${v.ok===true?"ok":v.ok===false?"err":"dim"}">wifi ${v.ok===true?"✓":v.ok===false?"✗":"—"}</td></tr>`;
  }).join("");
}
function line(topic,d,ev){
  if(paused)return;
  const row=document.createElement("div");row.className="row"+(ev?" ev":"")+(d&&(d.sev==="critical"||d.ok===false)?" bad":"");
  row.innerHTML=`<span class="ts">${new Date().toLocaleTimeString("en-GB",{hour12:false})}</span> ${esc(topic)} ${esc(JSON.stringify(d)).slice(0,220)}`;
  stream.insertBefore(row,stream.firstChild);
  while(stream.childElementCount>300)stream.lastChild.remove();
}
function esc(s){return String(s==null?"":s).replace(/[&<>]/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
setInterval(()=>{$("#rate").textContent=count+" msg/s";count=0;},1000);
$("#pause").onclick=(e)=>{paused=!paused;e.target.classList.toggle("on",paused);e.target.textContent=paused?"resume":"pause";};
$("#evonly").onclick=(e)=>{evonly=!evonly;e.target.classList.toggle("on",evonly);};
fetch("/healthz").then(r=>r.json()).then(h=>{window.__wsc=h.ws_clients;$("#v-ver").textContent=h.version;}).catch(()=>{});
connect();

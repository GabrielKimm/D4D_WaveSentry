/* All track positions arrive from the native synthetic model. Imagery is historical. */
'use strict';
const $=id=>document.getElementById(id);
const deg=x=>String(Math.round(x)%360).padStart(3,'0')+'°';
const arrow=x=>'↑↗→↘↓↙←↖'[Math.floor((x+22.5)/45)%8];
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
let viewer,bridge,frame=null,layer,localFrame,centerWorld,provider;
let tone='muted',firstTiles=false,providerFailed=false,lastFrame=0,placed=[],hits=[],drawing=false,overlayPending=false;
const metrics={ready:false,tiles:false,tileErrors:0,frames:0,sceneFrames:0,labelOverlaps:0,furnitureOverlaps:0,chromeOverlaps:0,labels:[],errors:[]};
// Read-only QA telemetry, no command or network control surface.
window.satelliteDiagnostics=()=>({...metrics,cameraHeight:viewer?.camera.positionCartographic.height,
    imageryCount:viewer?.imageryLayers.length,selected:frame?.selected,stale:frame?.stale,
    mode:frame?.mode,trackCount:frame?.tracks.length,tone,version:Cesium.VERSION,scenarioTime:frame?.scenarioTime,
    activeIds:frame?.tracks.map(d=>d.id),pulseCount:frame?.spotPulses?.length||0,
    cachedLabels:$('labels').childElementCount});

function status(kind,message){
  if(bridge)bridge.reportStatus(kind,message);
  if(kind==='error'){
    metrics.errors.push(message);providerFailed=true;
    $('loading').style.display='block';$('loading').querySelector('h2').textContent='위성영상 연결을 확인하세요';
    $('loading').querySelector('p').textContent='개략 지도로 전환합니다. 지도 상단에서 다시 연결할 수 있습니다.';
  }
}
window.addEventListener('error',e=>status('error',String(e.message)));
window.addEventListener('unhandledrejection',e=>status('error',String(e.reason?.message||e.reason)));

function world(x,y){
  return Cesium.Matrix4.multiplyByPoint(localFrame,new Cesium.Cartesian3(x,y,0),new Cesium.Cartesian3());
}
function project(x,y){
  const point=Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,world(x,y));
  return point&&Number.isFinite(point.x)&&Number.isFinite(point.y)?{x:point.x,y:point.y}:null;
}
function home(){
  if(!viewer)return;
  // North-up, ellipsoid only. No terrain/buildings or actual asset overlays.
  const c=frame?.center||{longitude:128.6588888888889,latitude:35.89416666666667};
  viewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(c.longitude,c.latitude,6400),
    orientation:{heading:0,pitch:-Math.PI/2,roll:0}});
  viewer.scene.requestRender();
}
function applyTone(){
  if(!layer)return;
  layer.brightness=tone==='muted'?.72:1.0;
  layer.contrast=tone==='muted'?1.12:1.0;
  layer.saturation=tone==='muted'?.32:.95;
  layer.gamma=1.0;
  $('tone').textContent=tone==='muted'?'영상':'선명';
  viewer.scene.requestRender();
}
function receive(raw){
  const next=JSON.parse(raw);
  if(next.site!=='airbase')return;
  frame=next;lastFrame=performance.now();
  if(!localFrame){
    centerWorld=Cesium.Cartesian3.fromDegrees(next.center.longitude,next.center.latitude,0);
    localFrame=Cesium.Transforms.eastNorthUpToFixedFrame(centerWorld);
  }
  setText($('rx-state'),next.stale?'LAST':'LIVE');
  for(const [id,kind] of [['total',null],['friendly','아군'],['hostile','적군'],['unknown','미식별']])
    setText($('count-'+id),String(kind?next.tracks.filter(d=>d.affiliation===kind).length:next.tracks.length).padStart(2,'0'));
  const active=new Set(next.tracks.map(d=>d.id));
  for(const el of $('labels').children)if(!active.has(el.id.slice(6)))el.hidden=true;
  const stateColor=next.stale?'#adb8bf':'';
  if($('rx-state').style.color!==stateColor)$('rx-state').style.color=stateColor;
  requestOverlay();
}
function requestOverlay(){
  if(overlayPending)return;
  overlayPending=true;
  requestAnimationFrame(()=>{overlayPending=false;render();});
}
function setText(el,value){if(el.textContent!==value)el.textContent=value;}
function geometry(c,pts,color,width=1,dash=[]){
  c.beginPath();let open=false;
  for(const [x,y] of pts){const p=project(x,y);if(!p){open=false;continue;}if(open)c.lineTo(p.x,p.y);else{c.moveTo(p.x,p.y);open=true;}}
  c.setLineDash(dash);c.strokeStyle='#08151cbb';c.lineWidth=width+2.5;c.stroke();
  c.strokeStyle=color;c.lineWidth=width;c.stroke();c.setLineDash([]);
}
function line(c,a,b,color,width=1,dash=[]){
  c.beginPath();c.moveTo(a.x,a.y);c.lineTo(b.x,b.y);c.strokeStyle=color;c.lineWidth=width;c.setLineDash(dash);c.stroke();c.setLineDash([]);
}
function ring(c,r,color,width=1,dash=[]){
  geometry(c,Array.from({length:97},(_,i)=>[Math.cos(i*Math.PI/48)*r,Math.sin(i*Math.PI/48)*r]),color,width,dash);
}
function text(c,s,x,y,color='#b7c8d0',font='10px Consolas'){
  c.font=font;c.fillStyle=color;c.shadowColor='#07131c';c.shadowBlur=5;c.fillText(s,x,y);c.shadowBlur=0;
}
// A single cached radial texture, composited on the existing 20 Hz overlay.
// No CSS blur, additional animation loop, WebGL invalidation, or growing entities.
const spotHalo=document.createElement('canvas');spotHalo.width=spotHalo.height=512;
{
  const c=spotHalo.getContext('2d'),g=c.createRadialGradient(256,256,0,256,256,256);
  for(const [at,alpha] of [[0,0],[.81,0],[.85,.18],[.87,.58],[.91,.22],[1,0]])
    g.addColorStop(at,`rgba(255,69,87,${alpha})`);
  c.fillStyle=g;c.fillRect(0,0,512,512);
}
function drawSpots(c,rx){
  const pulses=frame.spotPulses||[];
  if(!pulses.length||frame.stale)return;
  const east=project(frame.radius,0),north=project(0,frame.radius);
  if(!east||!north)return;
  const rw=Math.hypot(east.x-rx.x,east.y-rx.y),rh=Math.hypot(north.x-rx.x,north.y-rx.y);
  for(const pulse of pulses){
    const p=clamp(pulse.age/frame.spotDuration,0,1),alpha=Math.sin(Math.PI*p)**.85;
    const scale=1.2*(1+.035*p),a=pulse.bearing*Math.PI/180;
    c.save();c.globalAlpha=alpha*.85;
    c.drawImage(spotHalo,rx.x-rw*scale,rx.y-rh*scale,rw*scale*2,rh*scale*2);c.restore();
    const arc=Array.from({length:25},(_,i)=>{
      const b=a-.24+i*.02,r=frame.radius*(1.04+.025*p);return[Math.sin(b)*r,Math.cos(b)*r];});
    c.save();c.globalAlpha=alpha;geometry(c,arc,'#ff6472cc',1.6);c.restore();
    const d=frame.tracks.find(d=>d.id===pulse.id);
    const pos=d&&!d.bearingOnly?project(d.x,d.y):null;
    if(pos){c.beginPath();c.arc(pos.x,pos.y,12+p*17,0,Math.PI*2);c.strokeStyle=`rgba(255,107,116,${alpha*.65})`;c.lineWidth=1.2;c.stroke();}
  }
}
const intersects=(a,b)=>Math.max(0,Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y));
function rect(el){const r=el.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};}
function labelFor(d){
  let el=$('label-'+d.id);
  if(!el){
    el=document.createElement('button');el.id='label-'+d.id;el.className='track-label';
    el.innerHTML='<div class="head"><span class="mark"></span><span class="ident"></span><span class="kind"></span></div><div class="motion"><span class="primary"></span><span class="secondary"></span></div><div class="detail"></div>';
    el.parts=Object.fromEntries(['mark','ident','kind','primary','secondary','detail'].map(name=>[name,el.querySelector('.'+name)]));
    el.onclick=()=>bridge?.selectTrack(d.id);$('labels').append(el);
  }
  const selected=d.id===frame.selected,stale=frame.stale,color=stale?'#adbdc5':d.color;
  if(el.style.getPropertyValue('--ink')!==color)el.style.setProperty('--ink',color);
  if(el.getAttribute('aria-pressed')!==String(selected))el.setAttribute('aria-pressed',String(selected));
  if(el.dataset.stale!==String(stale))el.dataset.stale=String(stale);
  const symbol=d.affiliation==='아군'?'△':d.affiliation==='적군'?'◇':'○';
  setText(el.parts.mark,symbol);setText(el.parts.ident,d.id);setText(el.parts.kind,d.affiliation);
  setText(el.parts.primary,stale?`LAST ${Math.floor(frame.age)}s`:d.bearingOnly?`BRG ${deg(d.bearing)}`:`${d.speed.toFixed(1)} m/s`);
  setText(el.parts.secondary,stale?'— m/s · —°':d.bearingOnly?'거리 미확정':`${arrow(d.course)} ${deg(d.course)}`);
  el.parts.detail.hidden=!(selected||frame.allLabels);
  setText(el.parts.detail,d.bearingOnly?'방향 정보만 유효':`R ${Math.round(d.distance)} m · BRG ${deg(d.bearing)}`);
  const description=`${d.id} ${d.affiliation}, ${d.bearingOnly?'방위 '+deg(d.bearing):Math.round(d.distance)+' 미터'}, ${stale?'마지막 관측':d.bearingOnly?'위치 미확정':d.speed.toFixed(1)+' 미터 매초, 진행 '+deg(d.course)}`;
  if(el.getAttribute('aria-label')!==description)el.setAttribute('aria-label',description);
  return el;
}

function render(){
  if(!viewer||!frame||!localFrame||drawing)return;
  drawing=true;
  try{
    const canvas=$('tracks'),w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio||1,2);
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
    const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,w,h);
    c.lineCap='round';c.lineJoin='round';
    const rx=project(0,0);if(!rx)return;
    // Fixed geometry remains synthetic; presentation labels are kept concise.
    ring(c,frame.radius,'#d5e9ea25',.8,[2,10]);ring(c,frame.radius*.5,'#d5e9ea20',.8,[2,10]);
    ring(c,frame.zone,'#e4cf87b0',1.1,[4,7]);
    drawSpots(c,rx);
    const zn=project(0,frame.zone);if(zn)text(c,`보호구역 · ${frame.zone} m`,zn.x-55,zn.y-12,'#e4d69d','10px "Segoe UI"');
    const furniture=[...document.querySelectorAll('.map-heading,.track-summary,.map-controls,.layer-note,.scale,.legend')].map(rect);
    const positions=new Map();
    for(const d of frame.tracks){
      const bearing=d.bearing*Math.PI/180;
      const p=d.bearingOnly?project(Math.sin(bearing)*frame.radius*.78,Math.cos(bearing)*frame.radius*.78):project(d.x,d.y);
      if(p)positions.set(d.id,p);
    }
    placed=[...furniture,{x:rx.x-40,y:rx.y-14,w:80,h:52},...Array.from(positions.values()).map(p=>({x:p.x-15,y:p.y-15,w:30,h:30}))];
    if(zn)placed.push({x:zn.x-57,y:zn.y-24,w:118,h:20});
    hits=[];const labels=[];
    const ordered=[...frame.tracks].sort((a,b)=>(b.id===frame.selected)-(a.id===frame.selected));
    for(const d of ordered){
      const p=positions.get(d.id),el=labelFor(d);if(!p){el.hidden=true;continue;}
      const selected=d.id===frame.selected,color=frame.stale?'#a8bbc3':d.color;
      if(d.bearingOnly){
        const a=d.bearing*Math.PI/180;
        c.beginPath();c.moveTo(rx.x,rx.y);
        for(let i=-10;i<=10;i++){const ang=a+i*.012,pt=project(Math.sin(ang)*frame.radius,Math.cos(ang)*frame.radius);if(pt)c.lineTo(pt.x,pt.y);}
        c.closePath();c.fillStyle=color+'16';c.fill();c.strokeStyle=color+'66';c.lineWidth=1;c.stroke();
        const end=project(Math.sin(a)*frame.radius,Math.cos(a)*frame.radius);if(end)line(c,rx,end,color+'99',1,[5,7]);
      }else{
        if(frame.trails){
          for(let i=1;i<d.trail.length;i++){
            const alpha=(.14+i/d.trail.length*.76)*(frame.stale?.6:1);
            geometry(c,[d.trail[i-1],d.trail[i]],color+Math.round(alpha*255).toString(16).padStart(2,'0'),selected?1.9:1.35,frame.stale?[2,4]:[]);
            if(i%5===0){const dot=project(...d.trail[i]);if(dot){c.beginPath();c.arc(dot.x,dot.y,1.6,0,Math.PI*2);c.fillStyle=color+'bb';c.fill();}}
          }
        }
        if(selected){
          line(c,rx,p,color+'55',.9,[3,7]);
          if(frame.uncertainty&&!frame.stale){
            const edge=project(d.x+frame.error,d.y);const error=edge?Math.hypot(edge.x-p.x,edge.y-p.y):0;
            c.beginPath();c.arc(p.x,p.y,error,0,Math.PI*2);c.fillStyle=color+'20';c.fill();c.strokeStyle=color+'88';c.lineWidth=.8;c.stroke();
          }
          for(const sx of[-1,1])for(const sy of[-1,1]){line(c,{x:p.x+sx*9,y:p.y+sy*15},{x:p.x+sx*15,y:p.y+sy*15},color,1.1);line(c,{x:p.x+sx*15,y:p.y+sy*15},{x:p.x+sx*15,y:p.y+sy*9},color,1.1);}
        }
        const end=d.vx===null?null:project(d.x+d.vx*20,d.y+d.vy*20);
        const previous=d.trail.length>1?project(...d.trail[d.trail.length-2]):null;
        let a=previous?Math.atan2(p.y-previous.y,p.x-previous.x):0;
        if(end){a=Math.atan2(end.y-p.y,end.x-p.x);line(c,p,end,color+'cc',1.2);for(const da of[-.45,.45])line(c,end,{x:end.x-Math.cos(a+da)*7,y:end.y-Math.sin(a+da)*7},color,1.2);}
        c.save();c.translate(p.x,p.y);c.shadowColor='#06121c';c.shadowBlur=7;c.lineWidth=1.8;c.strokeStyle=color;c.fillStyle='#11222d';c.beginPath();
        if(d.affiliation==='아군'){c.rotate(a+Math.PI/2);c.moveTo(0,-8);c.lineTo(6,6);c.lineTo(0,2);c.lineTo(-6,6);c.closePath();}
        else if(d.affiliation==='적군'){c.moveTo(0,-7);c.lineTo(7,0);c.lineTo(0,7);c.lineTo(-7,0);c.closePath();}
        else c.arc(0,0,5.5,0,Math.PI*2);
        c.fill();c.stroke();c.restore();
      }
      // Suppress labels when their tracks leave the view, rather than pinning false positions to an edge.
      el.hidden=p.x<0||p.x>w||p.y<0||p.y>h-8;
      if(el.hidden)continue;
      const bw=el.offsetWidth,bh=el.offsetHeight;
      const candidates=[[p.x+24,p.y-bh-16],[p.x+24,p.y+17],[p.x-bw-24,p.y-bh-16],[p.x-bw-24,p.y+17],
        [p.x-bw/2,p.y-bh-32],[p.x-bw/2,p.y+32],[p.x+43,p.y-bh/2],[p.x-bw-43,p.y-bh/2]];
      for(let x=8;x<w-bw-8;x+=22)for(let y=8;y<h-bh-8;y+=18)candidates.push([x,y]);
      // Hold a collision-free relative anchor instead of picking a new side
      // whenever fractional distance or a rounded number changes.
      const anchor=el.anchor;
      if(anchor && anchor.w===bw && anchor.h===bh){
        const r={x:p.x+anchor.dx,y:p.y+anchor.dy,w:bw,h:bh};
        const padded={x:r.x-5,y:r.y-5,w:r.w+10,h:r.h+10};
        if(r.x>=8&&r.y>=8&&r.x+bw<=w-8&&r.y+bh<=h-8 &&
          !placed.some(a=>intersects(padded,a)>0)) candidates.splice(0,candidates.length,[r.x,r.y]);
      }
      let best;
      for(const [x,y] of candidates){const r={x:clamp(x,8,w-bw-8),y:clamp(y,8,h-bh-8),w:bw,h:bh};
        const padded={x:r.x-5,y:r.y-5,w:r.w+10,h:r.h+10};
        const score=placed.reduce((s,a)=>s+intersects(padded,a)*50,0)+Math.hypot(r.x+bw/2-p.x,r.y+bh/2-p.y);
        if(!best||score<best.score)best={...r,score};}
      el.style.left=Math.round(best.x)+'px';el.style.top=Math.round(best.y)+'px';
      el.anchor={dx:best.x-p.x,dy:best.y-p.y,w:bw,h:bh};
      placed.push(best);labels.push({id:d.id,...best});
      const near={x:clamp(p.x,best.x,best.x+bw),y:clamp(p.y,best.y,best.y+bh)};
      line(c,p,near,color+'88',.8);
      hits.push({id:d.id,x:p.x,y:p.y});
    }
    c.fillStyle='#152c36';c.strokeStyle='#c4eeea';c.lineWidth=1.1;c.fillRect(rx.x-6,rx.y-6,12,12);c.strokeRect(rx.x-6,rx.y-6,12,12);
    c.fillStyle='#a4e3ce';for(const x of[-2,2])for(const y of[-2,2])c.fillRect(rx.x+x-1,rx.y+y-1,2,2);
    text(c,'RX-A · 고정 어레이',rx.x-37,rx.y+25,'#c9e1e2','10px "Segoe UI"');
    const s0=project(0,0),s1=project(500,0);
    if(s0&&s1){const pixels=Math.hypot(s1.x-s0.x,s1.y-s0.y),meters=pixels>110?200:pixels<30?1000:500;
      setText($('scale-text'),meters+' m');const width=Math.round(pixels*meters/500)+'px';
      if($('scale-line').style.width!==width)$('scale-line').style.width=width;}
    metrics.frames++;metrics.labels=labels;metrics.labelOverlaps=labels.reduce((n,a,i)=>n+labels.slice(i+1).filter(b=>intersects(a,b)>0).length,0);
    metrics.furnitureOverlaps=labels.reduce((n,a)=>n+furniture.filter(b=>intersects(a,b)>0).length,0);
    metrics.chromeOverlaps=furniture.reduce((n,a,i)=>n+furniture.slice(i+1).filter(b=>intersects(a,b)>0).length,0);
    const age=performance.now()-lastFrame;
    if(age>2500){$('rx-state').textContent='DATA STALE';$('rx-state').style.color='#e4cf87';}
  }finally{drawing=false;}
}

async function init(){
  Cesium.Ion.defaultAccessToken='';
  // Keep Cesium's required credit host detached from the application's HUD.
  const credits=document.createElement('div');
  viewer=new Cesium.Viewer('globe',{baseLayer:false,animation:false,timeline:false,baseLayerPicker:false,
    geocoder:false,homeButton:false,sceneModePicker:false,navigationHelpButton:false,fullscreenButton:false,
    selectionIndicator:false,infoBox:false,requestRenderMode:true,maximumRenderTimeChange:Infinity,
    creditContainer:credits,creditViewport:credits,terrainProvider:new Cesium.EllipsoidTerrainProvider(),
    skyBox:false,skyAtmosphere:false,shouldAnimate:false,contextOptions:{webgl:{alpha:false,preserveDrawingBuffer:true}}});
  viewer.scene.backgroundColor=Cesium.Color.fromCssColorString('#0c151c');
  viewer.scene.globe.baseColor=Cesium.Color.fromCssColorString('#101b24');
  viewer.scene.globe.enableLighting=false;viewer.scene.globe.showGroundAtmosphere=false;
  viewer.scene.fog.enabled=false;viewer.scene.globe.maximumScreenSpaceError=1.4;
  viewer.resolutionScale=Math.min(devicePixelRatio||1,1.5);viewer.targetFrameRate=30;
  const controls=viewer.scene.screenSpaceCameraController;
  controls.enableTilt=false;controls.enableLook=false;controls.minimumZoomDistance=900;controls.maximumZoomDistance=28000;
  viewer.scene.postRender.addEventListener(()=>{metrics.sceneFrames++;requestOverlay();});
  viewer.scene.renderError.addEventListener((scene,error)=>status('error',String(error.message||error)));
  home();metrics.ready=true;status('ready','Cesium renderer ready');
  provider=await Cesium.ArcGisMapServerImageryProvider.fromUrl('https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer',
    {enablePickFeatures:false});
  provider.errorEvent.addEventListener(error=>{
    metrics.tileErrors++;$('imagery-state').textContent='일부 타일 재시도';
    if(error.timesRetried<2)error.retry=true;
    if(!firstTiles&&metrics.tileErrors>10)status('error','Esri 타일을 가져오지 못했습니다.');
  });
  layer=viewer.imageryLayers.addImageryProvider(provider);applyTone();
  let observedLoading=false;
  viewer.scene.globe.tileLoadProgressEvent.addEventListener(count=>{
    if(count>0){observedLoading=true;$('imagery-state').textContent='타일 갱신 중';}
    if(count===0&&observedLoading){
      if(!firstTiles){firstTiles=true;metrics.tiles=true;$('loading').style.display='none';status('tiles','Esri World Imagery loaded');}
      $('imagery-state').textContent='영상 연결됨';
    }
  });
  viewer.scene.requestRender();
  $('home').onclick=home;
  $('zoom-in').onclick=()=>{const h=viewer.camera.positionCartographic.height;viewer.camera.zoomIn(Math.max(0,Math.min(h*.25,h-900)));viewer.scene.requestRender();};
  $('zoom-out').onclick=()=>{const h=viewer.camera.positionCartographic.height;viewer.camera.zoomOut(Math.max(0,Math.min(h*.3,28000-h)));viewer.scene.requestRender();};
  $('north').onclick=()=>{viewer.camera.setView({orientation:{heading:0,pitch:-Math.PI/2,roll:0}});viewer.scene.requestRender();};
  $('tone').onclick=()=>{tone=tone==='muted'?'natural':'muted';applyTone();};
  const handler=new Cesium.ScreenSpaceEventHandler(viewer.canvas);
  handler.setInputAction(e=>{const hit=hits.find(p=>Math.hypot(p.x-e.position.x,p.y-e.position.y)<16);if(hit)bridge?.selectTrack(hit.id);},Cesium.ScreenSpaceEventType.LEFT_CLICK);
  window.addEventListener('resize',()=>viewer.scene.requestRender());
}
if(window.qt?.webChannelTransport){
  new QWebChannel(qt.webChannelTransport,channel=>{bridge=channel.objects.mapBridge;bridge.telemetry.connect(receive);init().catch(e=>status('error',e.message));});
}else{
  $('loading').querySelector('h2').textContent='Windows 앱에서 열어주세요';
  $('loading').querySelector('p').textContent='이 지도는 WaveSentry의 관측 데이터에 연결됩니다.';
}

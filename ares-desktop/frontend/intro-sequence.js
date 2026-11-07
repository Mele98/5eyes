// Stack-sichere Min/Max (A1-Root-Fix): Math.min/max.apply(null, arr) legt JEDES
// Array-Element als eigenes Funktions-Argument auf den Stack — bei sehr langen Serien
// (z.B. viele Projektionsjahre/monatlich) wirft V8 "RangeError: Maximum call stack
// size exceeded". Diese schleifenbasierten Varianten sind size-unabhaengig und bei
// normalen Groessen verhaltensidentisch (leeres Array -> +/-Infinity wie Math.min/max()).
function arrMin(a){var m=Infinity;for(var i=0;i<a.length;i++){var n=Number(a[i]);if(n<m)m=n;}return m;}
function arrMax(a){var m=-Infinity;for(var i=0;i<a.length;i++){var n=Number(a[i]);if(n>m)m=n;}return m;}
(function(){
  try{window.replayIntro=function(){try{sessionStorage.removeItem('introShown');}catch(e){}location.reload();};}catch(e){}
  var intro=document.getElementById('intro-screen');
  if(!intro)return;
  var force=(location.search||'').indexOf('intro=1')>=0;
  try{
    if(!force&&sessionStorage.getItem('introShown')==='1'){intro.parentNode&&intro.parentNode.removeChild(intro);return;}
    sessionStorage.setItem('introShown','1');
  }catch(e){}
  var reduce=false;
  try{reduce=!!(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches);}catch(e){}
  var canvas=document.getElementById('intro-world');
  var ctx=canvas&&canvas.getContext?canvas.getContext('2d'):null;
  var logEl=intro.querySelector('.intro-log');
  var bar=intro.querySelector('.intro-progress > i');
  var clockEl=intro.querySelector('.intro-clock');
  var continueButton=intro.querySelector('.intro-skip');
  var steps=['Wealth structure mapping','Strategic allocation synchronized','Private markets and liquidity mapped','Risk budget and goals validated','Advisory environment ready'];
  var done=false,ready=false,raf=0,clockTimer=0,calmTimer=0,start=performance.now();
  var countryOutlines=Array.isArray(window.INTRO_COUNTRY_OUTLINES)?window.INTRO_COUNTRY_OUTLINES:[];
  var continents=[
    [[-168,70],[-145,62],[-128,50],[-123,38],[-105,25],[-88,18],[-82,26],[-70,44],[-55,53],[-74,68],[-110,73]],
    [[-81,12],[-72,5],[-68,-12],[-55,-24],[-53,-38],[-67,-55],[-75,-35],[-79,-12]],
    [[-12,35],[-2,51],[18,60],[42,56],[63,67],[95,72],[125,55],[150,48],[142,35],[115,22],[92,10],[72,22],[48,31],[34,29],[28,40],[12,43]],
    [[-17,34],[4,37],[24,31],[39,12],[34,-10],[19,-35],[2,-32],[-11,-4]],
    [[112,-12],[132,-10],[153,-25],[146,-40],[121,-35]],
    [[-52,82],[-25,76],[-37,61],[-58,64]]
  ];
  var continentCenters=[
    {lon:-108,lat:49,label:'NORTH AMERICA'},
    {lon:-63,lat:-20,label:'SOUTH AMERICA'},
    {lon:65,lat:45,label:'EUROPE & ASIA'},
    {lon:18,lat:4,label:'AFRICA'},
    {lon:134,lat:-26,label:'OCEANIA'},
    {lon:-42,lat:71,label:'GREENLAND'}
  ];
  function countryRegionIndex(country){
    if(country.n==='Greenland')return 5;
    return {
      'North America':0,
      'South America':1,
      'Europe':2,
      'Asia':2,
      'Africa':3,
      'Oceania':4
    }[country.c]||2;
  }
  var countryShapes=countryOutlines.map(function(country){
    return {
      name:country.n,
      region:countryRegionIndex(country),
      bbox:country.b,
      rings:country.p
    };
  });
  var globeTexture=[];
  for(var textureIndex=0;textureIndex<320;textureIndex++){
    var textureUnit=((textureIndex*97)%317)/316;
    globeTexture.push([
      ((textureIndex*137.508)%360)-180,
      Math.asin(textureUnit*2-1)*180/Math.PI,
      .12+((textureIndex*29)%17)/100
    ]);
  }
  function pointInPolygon(lon,lat,polygon){
    var inside=false;
    for(var i=0,j=polygon.length-1;i<polygon.length;j=i++){
      var xi=polygon[i][0],yi=polygon[i][1],xj=polygon[j][0],yj=polygon[j][1];
      var intersects=((yi>lat)!==(yj>lat))&&(lon<(xj-xi)*(lat-yi)/((yj-yi)||.00001)+xi);
      if(intersects)inside=!inside;
    }
    return inside;
  }
  function pointInCountry(lon,lat,country){
    var bbox=country.bbox;
    if(bbox&&(lon<bbox[0]||lat<bbox[1]||lon>bbox[2]||lat>bbox[3]))return false;
    var inside=false;
    for(var ringIndex=0;ringIndex<country.rings.length;ringIndex++){
      if(pointInPolygon(lon,lat,country.rings[ringIndex]))inside=!inside;
    }
    return inside;
  }
  var hexLandTiles=[];
  for(var tileLat=-56,row=0;tileLat<=80;tileLat+=4.5,row++){
    for(var tileLon=-177+(row%2?2.6:0);tileLon<=177;tileLon+=5.2){
      var onLand=false,continentIndex=-1,countryIndex=-1;
      if(countryShapes.length){
        for(var shapeIndex=0;shapeIndex<countryShapes.length;shapeIndex++){
          if(pointInCountry(tileLon,tileLat,countryShapes[shapeIndex])){
            onLand=true;
            countryIndex=shapeIndex;
            continentIndex=countryShapes[shapeIndex].region;
            break;
          }
        }
      }else{
        for(var polygonIndex=0;polygonIndex<continents.length;polygonIndex++){
          if(pointInPolygon(tileLon,tileLat,continents[polygonIndex])){onLand=true;continentIndex=polygonIndex;break;}
        }
      }
      if(onLand){
        var tileSeed=Math.abs(Math.round(tileLon*13+tileLat*29));
        hexLandTiles.push({
          lon:tileLon,
          lat:tileLat,
          continent:continentIndex,
          country:countryIndex,
          lift:.027+(tileSeed%7)*.003,
          phase:(tileSeed%31)*.19,
          accent:tileSeed%19===0||tileSeed%23===0
        });
      }
    }
  }
  var marketHubs=[
    {lon:8,lat:47,label:'ZRH'},
    {lon:-74,lat:40,label:'NYC'},
    {lon:103,lat:1,label:'SGP'},
    {lon:139,lat:35,label:'TYO'},
    {lon:-46,lat:-23,label:'SAO'}
  ];
  var marketLinks=[[0,1],[0,2],[0,3],[1,4],[2,3]];
  var capitalCities=[
    {lon:7.45,lat:46.95,label:'BERN'},
    {lon:-.13,lat:51.51,label:'LONDON'},
    {lon:2.35,lat:48.86,label:'PARIS'},
    {lon:13.41,lat:52.52,label:'BERLIN'},
    {lon:-77.04,lat:38.91,label:'WASHINGTON'},
    {lon:-75.70,lat:45.42,label:'OTTAWA'},
    {lon:-47.88,lat:-15.79,label:'BRASILIA'},
    {lon:54.38,lat:24.45,label:'ABU DHABI'},
    {lon:77.21,lat:28.61,label:'NEW DELHI'},
    {lon:116.41,lat:39.90,label:'BEIJING'},
    {lon:139.69,lat:35.68,label:'TOKYO'},
    {lon:103.82,lat:1.35,label:'SINGAPORE'},
    {lon:151.21,lat:-33.87,label:'CANBERRA'}
  ];
  function finish(){
    if(done||!ready)return;
    done=true;
    if(raf)cancelAnimationFrame(raf);
    if(clockTimer)clearInterval(clockTimer);
    if(calmTimer)clearTimeout(calmTimer);
    window.removeEventListener('resize',resize);
    window.removeEventListener('keydown',handleKey);
    intro.classList.add('intro-hide');
    setTimeout(function(){try{intro.parentNode&&intro.parentNode.removeChild(intro);}catch(e){}},760);
  }
  function markReady(){
    if(done||ready)return;
    ready=true;
    intro.classList.add('intro-ready');
    if(logEl)logEl.textContent='System ready · click to enter';
    if(bar)bar.style.width='100%';
    if(continueButton){
      continueButton.disabled=false;
      continueButton.textContent='KLICKEN ZUM STARTEN';
    }
  }
  function handleKey(event){
    if(ready&&(event.key==='Enter'||event.key===' ')){
      event.preventDefault();
      finish();
    }
  }
  function cinematicTime(rawTime){
    var revealEnd=2400,settleEnd=6000;
    if(rawTime<=revealEnd)return rawTime;
    if(rawTime>=settleEnd){
      var settledDistance=(settleEnd-revealEnd)*(.59);
      return revealEnd+settledDistance+(rawTime-settleEnd)*.12;
    }
    var duration=settleEnd-revealEnd;
    var progress=(rawTime-revealEnd)/duration;
    var easedIntegral=progress-.82*(progress*progress*progress-.5*progress*progress*progress*progress);
    return revealEnd+duration*easedIntegral;
  }
  function resize(){
    if(!canvas||!ctx)return;
    var dpr=Math.min(window.devicePixelRatio||1,2);
    canvas.width=Math.round(innerWidth*dpr);
    canvas.height=Math.round(innerHeight*dpr);
    canvas.style.width=innerWidth+'px';
    canvas.style.height=innerHeight+'px';
    ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function project(lon,lat,rotation,cx,cy,r){
    var lo=(lon+rotation)*Math.PI/180,la=lat*Math.PI/180,c=Math.cos(la);
    return{x:cx+r*c*Math.sin(lo),y:cy-r*Math.sin(la),z:c*Math.cos(lo)};
  }
  function pathGeo(points,rotation,cx,cy,r,close){
    var drawing=false;
    ctx.beginPath();
    for(var i=0;i<points.length;i++){
      var p=project(points[i][0],points[i][1],rotation,cx,cy,r);
      if(p.z>-.035){if(!drawing){ctx.moveTo(p.x,p.y);drawing=true;}else ctx.lineTo(p.x,p.y);}else drawing=false;
    }
    if(close&&drawing)ctx.closePath();
    return drawing;
  }
  function drawCountryGeometry(rotation,cx,cy,r,activeRegion,activeLift,outlineOnly,focusOnly){
    if(!countryShapes.length)return;
    for(var countryIndex=0;countryIndex<countryShapes.length;countryIndex++){
      var country=countryShapes[countryIndex];
      var bbox=country.bbox||[0,0,0,0];
      var centerLon=(bbox[0]+bbox[2])*.5;
      var centerLat=(bbox[1]+bbox[3])*.5;
      var centerPoint=project(centerLon,centerLat,rotation,cx,cy,r);
      var frontness=Math.max(0,Math.min(1,(centerPoint.z+.08)/1.08));
      if(frontness<=.015)continue;
      var isFocused=country.region===activeRegion;
      if(focusOnly&&!isFocused)continue;
      var countryRadius=r*(isFocused?activeLift:1.006);
      var fillAlpha=(.018+frontness*.052)*(isFocused?1.9:1);
      var strokeAlpha=.09+frontness*(isFocused?.38:.20);
      ctx.lineWidth=isFocused?.78:.48;
      ctx.fillStyle=isFocused
        ?'rgba(57,153,169,'+fillAlpha+')'
        :'rgba(34,112,130,'+fillAlpha+')';
      ctx.strokeStyle=isFocused
        ?'rgba(178,229,232,'+strokeAlpha+')'
        :'rgba(130,201,210,'+strokeAlpha+')';
      for(var ringIndex=0;ringIndex<country.rings.length;ringIndex++){
        if(pathGeo(country.rings[ringIndex],rotation,cx,cy,countryRadius,true)){
          if(!outlineOnly)ctx.fill();
          ctx.stroke();
        }
      }
    }
  }
  function drawSatellite(cx,cy,orbitRadius,t,tilt,phase,flatten){
    var angle=t*.00042+phase;
    var ox=Math.cos(angle)*orbitRadius,oy=Math.sin(angle)*orbitRadius*flatten;
    var cosTilt=Math.cos(tilt),sinTilt=Math.sin(tilt);
    var sx=cx+ox*cosTilt-oy*sinTilt,sy=cy+ox*sinTilt+oy*cosTilt;
    var tangent=Math.atan2(
      (-Math.sin(angle)*orbitRadius)*sinTilt+(Math.cos(angle)*orbitRadius*flatten)*cosTilt,
      (-Math.sin(angle)*orbitRadius)*cosTilt-(Math.cos(angle)*orbitRadius*flatten)*sinTilt
    );
    ctx.save();
    ctx.translate(cx,cy);ctx.rotate(tilt);ctx.scale(1,flatten);
    ctx.setLineDash([3,8]);ctx.lineDashOffset=-(t*.012);
    ctx.strokeStyle='rgba(116,195,209,.24)';ctx.lineWidth=.8;
    ctx.beginPath();ctx.arc(0,0,orbitRadius,0,Math.PI*2);ctx.stroke();
    ctx.restore();
    ctx.save();
    ctx.translate(sx,sy);ctx.rotate(tangent);
    ctx.shadowColor='rgba(84,198,216,.8)';ctx.shadowBlur=8;
    ctx.fillStyle='#b8d7dd';ctx.fillRect(-3.5,-2.2,7,4.4);
    ctx.fillStyle='rgba(67,156,177,.82)';ctx.fillRect(-12,-3.4,6.5,6.8);ctx.fillRect(5.5,-3.4,6.5,6.8);
    ctx.strokeStyle='rgba(202,232,236,.52)';ctx.lineWidth=.6;
    ctx.strokeRect(-12,-3.4,6.5,6.8);ctx.strokeRect(5.5,-3.4,6.5,6.8);
    ctx.fillStyle='#d5b45d';ctx.beginPath();ctx.arc(0,0,1.35,0,Math.PI*2);ctx.fill();
    ctx.restore();
    var pulse=8+((t*.025+phase*30)%12);
    ctx.strokeStyle='rgba(84,198,216,'+(Math.max(0,.28-(pulse-8)*.02))+')';
    ctx.lineWidth=.8;ctx.beginPath();ctx.arc(sx,sy,pulse,0,Math.PI*2);ctx.stroke();
  }
  function quadraticPoint(a,b,c,p){
    var q=1-p;
    return{x:q*q*a.x+2*q*p*b.x+p*p*c.x,y:q*q*a.y+2*q*p*b.y+p*p*c.y};
  }
  function drawHexagon(x,y,size,rotation,fill,stroke){
    ctx.beginPath();
    for(var side=0;side<6;side++){
      var angle=rotation+Math.PI/3*side;
      var hx=x+Math.cos(angle)*size,hy=y+Math.sin(angle)*size;
      if(!side)ctx.moveTo(hx,hy);else ctx.lineTo(hx,hy);
    }
    ctx.closePath();
    if(fill){ctx.fillStyle=fill;ctx.fill();}
    if(stroke){ctx.strokeStyle=stroke;ctx.stroke();}
  }
  function hexVertices(x,y,size,rotation){
    var vertices=[];
    for(var side=0;side<6;side++){
      var angle=rotation+Math.PI/3*side;
      vertices.push({x:x+Math.cos(angle)*size,y:y+Math.sin(angle)*size});
    }
    return vertices;
  }
  function drawHexExtrusion(baseX,baseY,topX,topY,size,rotation,alpha){
    var base=hexVertices(baseX,baseY,size*.88,rotation);
    var top=hexVertices(topX,topY,size,rotation);
    var directionX=topX-baseX,directionY=topY-baseY;
    var selected=[];
    for(var side=0;side<6;side++){
      var next=(side+1)%6;
      var edgeX=top[next].x-top[side].x,edgeY=top[next].y-top[side].y;
      if(edgeX*directionY-edgeY*directionX>0)selected.push(side);
    }
    for(var face=0;face<selected.length;face++){
      var faceIndex=selected[face],faceNext=(faceIndex+1)%6;
      var shade=.08+alpha*(face%2?.32:.48);
      ctx.fillStyle='rgba(28,105,121,'+shade+')';
      ctx.strokeStyle='rgba(123,211,220,'+Math.min(.42,shade+.08)+')';
      ctx.beginPath();
      ctx.moveTo(base[faceIndex].x,base[faceIndex].y);
      ctx.lineTo(base[faceNext].x,base[faceNext].y);
      ctx.lineTo(top[faceNext].x,top[faceNext].y);
      ctx.lineTo(top[faceIndex].x,top[faceIndex].y);
      ctx.closePath();ctx.fill();ctx.stroke();
    }
  }
  function drawDottedOrbit(cx,cy,radius,tilt,flatten,t,offset,color){
    ctx.save();
    ctx.translate(cx,cy);ctx.rotate(tilt);
    for(var dot=0;dot<84;dot++){
      var angle=Math.PI*2*dot/84+offset+t*.000035;
      var visibility=.28+.72*(.5+.5*Math.sin(angle));
      var dx=Math.cos(angle)*radius,dy=Math.sin(angle)*radius*flatten;
      var dotSize=dot%7===0?1.35:.65;
      ctx.globalAlpha=visibility;
      ctx.fillStyle=color;
      ctx.beginPath();ctx.arc(dx,dy,dotSize,0,Math.PI*2);ctx.fill();
    }
    ctx.restore();ctx.globalAlpha=1;
  }
  function drawWhirlField(cx,cy,r,t,w){
    var whirls=[
      {radius:1.02,spread:.42,turns:1.72,tilt:-.18,flatten:.70,phase:.2,color:'rgba(91,207,219,.20)',dash:[2,9]},
      {radius:1.11,spread:.34,turns:1.34,tilt:.52,flatten:.38,phase:2.1,color:'rgba(213,180,93,.15)',dash:[1,12]},
      {radius:1.18,spread:.30,turns:1.18,tilt:-.74,flatten:.24,phase:4.0,color:'rgba(156,181,190,.12)',dash:[4,14]}
    ];
    ctx.save();
    ctx.translate(cx,cy);
    for(var whirlIndex=0;whirlIndex<whirls.length;whirlIndex++){
      if(w<720&&whirlIndex>0)continue;
      var whirl=whirls[whirlIndex];
      ctx.save();
      ctx.rotate(whirl.tilt);
      ctx.scale(1,whirl.flatten);
      ctx.setLineDash(whirl.dash);
      ctx.lineDashOffset=-(t*.006+whirlIndex*7);
      ctx.strokeStyle=whirl.color;
      ctx.lineWidth=whirlIndex===0?1.05:.75;
      ctx.beginPath();
      for(var whirlStep=0;whirlStep<=150;whirlStep++){
        var whirlProgress=whirlStep/150;
        var angle=whirl.phase+t*(.000045-whirlIndex*.000008)+whirlProgress*Math.PI*2*whirl.turns;
        var radial=r*(whirl.radius+whirl.spread*whirlProgress);
        var wx=Math.cos(angle)*radial,wy=Math.sin(angle)*radial;
        if(!whirlStep)ctx.moveTo(wx,wy);else ctx.lineTo(wx,wy);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      for(var particle=0;particle<9;particle++){
        var particleProgress=(particle/9+t*.000012*(whirlIndex+1))%1;
        var particleAngle=whirl.phase+t*.00004+particleProgress*Math.PI*2*whirl.turns;
        var particleRadius=r*(whirl.radius+whirl.spread*particleProgress);
        ctx.globalAlpha=.22+.44*(1-particleProgress);
        ctx.fillStyle=whirlIndex===1?'#d5b45d':'#7bd4df';
        ctx.beginPath();
        ctx.arc(Math.cos(particleAngle)*particleRadius,Math.sin(particleAngle)*particleRadius,particle%3===0?1.35:.75,0,Math.PI*2);
        ctx.fill();
      }
      ctx.restore();
    }
    ctx.restore();
    ctx.globalAlpha=1;
    ctx.setLineDash([]);
  }
  function drawFinanceBackdrop(t,w,h){
    if(w<760)return;
    var left=w*.34,right=w*.965,top=h*.09,bottom=h*.87;
    ctx.save();
    ctx.globalAlpha=.22;
    ctx.font='600 7px ui-monospace,Consolas,monospace';
    var lanes=[
      {y:h*.23,label:'GLOBAL EQUITY / CHF',color:'rgba(84,198,216,.42)',phase:.4},
      {y:h*.49,label:'CREDIT SPREAD / LIQUIDITY',color:'rgba(213,180,93,.30)',phase:2.1},
      {y:h*.73,label:'PRIVATE MARKETS / REAL ASSETS',color:'rgba(115,185,170,.31)',phase:4.2}
    ];
    for(var laneIndex=0;laneIndex<lanes.length;laneIndex++){
      var lane=lanes[laneIndex];
      ctx.fillStyle='rgba(145,175,184,.54)';
      ctx.fillText(lane.label,left,lane.y-12);
      ctx.strokeStyle='rgba(105,157,170,.10)';
      ctx.lineWidth=.6;
      ctx.beginPath();ctx.moveTo(left,lane.y);ctx.lineTo(right,lane.y);ctx.stroke();
      ctx.strokeStyle=lane.color;
      ctx.lineWidth=1;
      ctx.beginPath();
      for(var pointIndex=0;pointIndex<=72;pointIndex++){
        var progress=pointIndex/72;
        var drift=Math.sin(progress*11+lane.phase+t*.00013)*9;
        var cycle=Math.sin(progress*27-lane.phase+t*.00008)*3.6;
        var trend=(progress-.5)*(laneIndex===1?-7:10);
        var px=left+(right-left)*progress;
        var py=lane.y+drift+cycle-trend;
        if(!pointIndex)ctx.moveTo(px,py);else ctx.lineTo(px,py);
      }
      ctx.stroke();
    }
    var candleBase=top+55,candleWidth=(right-left)/34;
    for(var candleIndex=0;candleIndex<34;candleIndex++){
      var energy=Math.sin(candleIndex*1.73+t*.00022);
      var center=candleBase+Math.sin(candleIndex*.58+t*.00011)*16;
      var high=9+Math.abs(Math.sin(candleIndex*2.2+t*.00016))*18;
      var body=3+Math.abs(Math.cos(candleIndex*1.14+t*.00009))*8;
      var candleX=left+candleIndex*candleWidth;
      var rising=energy>.02;
      ctx.strokeStyle=rising?'rgba(102,202,183,.24)':'rgba(218,104,94,.20)';
      ctx.fillStyle=rising?'rgba(102,202,183,.18)':'rgba(218,104,94,.15)';
      ctx.beginPath();ctx.moveTo(candleX,center-high);ctx.lineTo(candleX,center+high);ctx.stroke();
      ctx.fillRect(candleX-1.7,center-body*.5,3.4,body);
    }
    var volumeY=bottom,volumeHeight=h*.085;
    for(var volumeIndex=0;volumeIndex<44;volumeIndex++){
      var volumeProgress=volumeIndex/43;
      var volume=.18+.82*Math.abs(Math.sin(volumeIndex*.82+t*.00009));
      var volumeX=left+(right-left)*volumeProgress;
      ctx.fillStyle=volumeIndex%9===0?'rgba(213,180,93,.18)':'rgba(84,198,216,.11)';
      ctx.fillRect(volumeX,volumeY-volumeHeight*volume,3,volumeHeight*volume);
    }
    ctx.restore();
  }
  function drawWealthHud(t,w,h,cx,cy,r,activeCenter,activeLift,activeLabel){
    if(w<820)return;
    var labelX=cx-r*.88,labelY=cy-r*.73;
    var anchorX=cx+(activeCenter.x-cx)*activeLift;
    var anchorY=cy+(activeCenter.y-cy)*activeLift;
    ctx.strokeStyle='rgba(213,180,93,.46)';ctx.lineWidth=.8;
    ctx.beginPath();ctx.moveTo(anchorX,anchorY);ctx.lineTo(labelX+42,labelY+14);ctx.lineTo(labelX,labelY+14);ctx.stroke();
    ctx.fillStyle='rgba(213,180,93,.9)';ctx.beginPath();ctx.arc(anchorX,anchorY,2.1,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='rgba(155,184,194,.62)';ctx.font='600 7px ui-monospace,Consolas,monospace';
    ctx.fillText('CROSS-BORDER WEALTH',labelX,labelY);
    ctx.fillStyle='rgba(224,233,235,.86)';ctx.font='600 9px ui-monospace,Consolas,monospace';
    ctx.fillText(activeLabel+' / REGION IN FOCUS',labelX,labelY+10);
    var ringX=cx+r*.72,ringY=cy-r*.72,ringR=24;
    var segments=[
      {a:-Math.PI*.5,b:Math.PI*.02,c:'rgba(84,198,216,.75)'},
      {a:Math.PI*.08,b:Math.PI*.56,c:'rgba(213,180,93,.72)'},
      {a:Math.PI*.62,b:Math.PI*1.04,c:'rgba(108,174,187,.55)'},
      {a:Math.PI*1.10,b:Math.PI*1.45,c:'rgba(190,211,218,.36)'}
    ];
    ctx.lineWidth=3.2;
    for(var segment=0;segment<segments.length;segment++){
      ctx.strokeStyle=segments[segment].c;ctx.beginPath();
      ctx.arc(ringX,ringY,ringR+segment*.15,segments[segment].a+t*.000035,segments[segment].b+t*.000035);ctx.stroke();
    }
    ctx.lineWidth=.7;ctx.strokeStyle='rgba(130,179,190,.24)';ctx.beginPath();ctx.arc(ringX,ringY,ringR+7,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle='rgba(185,205,212,.62)';ctx.font='600 7px ui-monospace,Consolas,monospace';
    ctx.fillText('MULTI-ASSET',ringX-23,ringY+42);
  }
  function drawStrategyBackdrop(t,w,h){
    if(w<900)return;
    var fade=Math.min(1,t/1800),x=w*.32,y=h*.13,panelW=Math.min(240,w*.18),panelH=112;
    ctx.save();ctx.globalAlpha=.15*fade;
    ctx.strokeStyle='rgba(115,183,197,.7)';ctx.fillStyle='rgba(7,20,29,.5)';ctx.lineWidth=.7;
    ctx.strokeRect(x,y,panelW,panelH);
    ctx.fillStyle='rgba(153,191,201,.85)';ctx.font='600 7px ui-monospace,Consolas,monospace';
    ctx.fillText('STRATEGIC ALLOCATION / POLICY VIEW',x+10,y+14);
    var allocationRows=[
      {label:'EQUITY',width:.78,color:'rgba(84,198,216,.78)'},
      {label:'FIXED INCOME',width:.58,color:'rgba(117,164,176,.65)'},
      {label:'PRIVATE MARKETS',width:.43,color:'rgba(213,180,93,.72)'},
      {label:'REAL ASSETS',width:.34,color:'rgba(115,185,170,.58)'},
      {label:'LIQUIDITY',width:.24,color:'rgba(188,205,211,.42)'}
    ];
    for(var rowIndex=0;rowIndex<allocationRows.length;rowIndex++){
      var row=allocationRows[rowIndex],rowY=y+29+rowIndex*15;
      ctx.fillStyle='rgba(143,169,178,.72)';ctx.fillText(row.label,x+10,rowY+4);
      ctx.fillStyle='rgba(255,255,255,.06)';ctx.fillRect(x+88,rowY,panelW-100,4);
      var breathing=.96+.04*Math.sin(t*.0011+rowIndex*.8);
      ctx.fillStyle=row.color;ctx.fillRect(x+88,rowY,(panelW-100)*row.width*breathing,4);
    }
    var frontierX=x+panelW+28,frontierY=y+8,frontierW=148,frontierH=88;
    ctx.strokeStyle='rgba(115,183,197,.46)';ctx.beginPath();
    ctx.moveTo(frontierX,frontierY+frontierH);ctx.lineTo(frontierX+frontierW,frontierY+frontierH);
    ctx.moveTo(frontierX,frontierY+frontierH);ctx.lineTo(frontierX,frontierY);ctx.stroke();
    ctx.fillStyle='rgba(153,191,201,.8)';ctx.fillText('EFFICIENT FRONTIER',frontierX,frontierY+8);
    ctx.beginPath();
    for(var frontierStep=0;frontierStep<=30;frontierStep++){
      var fp=frontierStep/30;
      var fx=frontierX+8+fp*(frontierW-14);
      var fy=frontierY+frontierH-8-(Math.sqrt(fp)*.78+fp*.12)*(frontierH-23);
      if(!frontierStep)ctx.moveTo(fx,fy);else ctx.lineTo(fx,fy);
    }
    ctx.strokeStyle='rgba(84,198,216,.82)';ctx.lineWidth=1.2;ctx.stroke();
    for(var frontierNode=0;frontierNode<5;frontierNode++){
      var nodeP=.12+frontierNode*.19;
      var nodeX=frontierX+8+nodeP*(frontierW-14);
      var nodeY=frontierY+frontierH-8-(Math.sqrt(nodeP)*.78+nodeP*.12)*(frontierH-23);
      ctx.fillStyle=frontierNode===2?'rgba(213,180,93,.95)':'rgba(121,208,219,.72)';
      ctx.beginPath();ctx.arc(nodeX,nodeY,frontierNode===2?2.3:1.5,0,Math.PI*2);ctx.fill();
    }
    ctx.restore();
  }
  function drawCapitalLights(t,w,rotation,cx,cy,r){
    var visible=[];
    for(var cityIndex=0;cityIndex<capitalCities.length;cityIndex++){
      var capital=capitalCities[cityIndex];
      var capitalPoint=project(capital.lon,capital.lat,rotation,cx,cy,r);
      if(capitalPoint.z>.1)visible.push({city:capital,point:capitalPoint,index:cityIndex});
    }
    if(!visible.length)return;
    var activeIndex=Math.floor(t/1180)%visible.length;
    for(var visibleCityIndex=0;visibleCityIndex<visible.length;visibleCityIndex++){
      var visibleCapital=visible[visibleCityIndex],point=visibleCapital.point;
      var isActive=visibleCityIndex===activeIndex;
      var outward=1.025+(isActive?.02:0);
      var lightX=cx+(point.x-cx)*outward,lightY=cy+(point.y-cy)*outward;
      var baseAlpha=.16+point.z*.34;
      if(isActive){
        var beam=ctx.createLinearGradient(lightX,lightY-26,lightX,lightY+3);
        beam.addColorStop(0,'rgba(213,180,93,0)');beam.addColorStop(1,'rgba(213,180,93,.42)');
        ctx.strokeStyle=beam;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(lightX,lightY-26);ctx.lineTo(lightX,lightY);ctx.stroke();
        var capitalPulse=7+((t*.025)%18);
        ctx.strokeStyle='rgba(213,180,93,'+Math.max(.03,.48-(capitalPulse-7)*.025)+')';
        ctx.beginPath();ctx.arc(lightX,lightY,capitalPulse,0,Math.PI*2);ctx.stroke();
        ctx.fillStyle='rgba(245,222,157,.98)';ctx.shadowColor='rgba(213,180,93,.9)';ctx.shadowBlur=10;
        ctx.beginPath();ctx.arc(lightX,lightY,2.5,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
        if(w>820){
          var labelRight=lightX<cx;
          ctx.strokeStyle='rgba(213,180,93,.42)';ctx.beginPath();ctx.moveTo(lightX+4,lightY-4);
          ctx.lineTo(lightX+(labelRight?22:-22),lightY-16);ctx.stroke();
          ctx.fillStyle='rgba(230,224,201,.9)';ctx.font='600 7px ui-monospace,Consolas,monospace';
          ctx.textAlign=labelRight?'left':'right';
          ctx.fillText(visibleCapital.city.label,lightX+(labelRight?25:-25),lightY-14);
          ctx.textAlign='left';
        }
      }else{
        ctx.fillStyle='rgba(174,217,222,'+baseAlpha+')';
        ctx.beginPath();ctx.arc(lightX,lightY,1.25,0,Math.PI*2);ctx.fill();
      }
    }
  }
  function drawGlobe(t,w,h){
    var cx=w<720?w*.68:w*.655,cy=h*.47,r=Math.min(w,h)*(w<720?.27:.335);
    var rotation=18+t*.0045;
    var centerProjections=[],activeContinent=0,activeScore=-2;
    for(var centerIndex=0;centerIndex<continentCenters.length;centerIndex++){
      var centerProjection=project(continentCenters[centerIndex].lon,continentCenters[centerIndex].lat,rotation,cx,cy,r);
      centerProjections.push(centerProjection);
      if(centerProjection.z>activeScore){activeScore=centerProjection.z;activeContinent=centerIndex;}
    }
    var detachProgress=reduce?1:Math.max(0,Math.min(1,(t-650)/2450));
    detachProgress=detachProgress*detachProgress*(3-2*detachProgress);
    var activeFrontness=Math.max(0,Math.min(1,(activeScore-.12)/.82));
    var activeLift=1+.155*detachProgress*activeFrontness*(.96+.04*Math.sin(t*.0012));
    var halo=ctx.createRadialGradient(cx,cy,r*.22,cx,cy,r*1.28);
    halo.addColorStop(0,'rgba(60,170,190,.13)');halo.addColorStop(.72,'rgba(13,58,75,.05)');halo.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=halo;ctx.beginPath();ctx.arc(cx,cy,r*1.28,0,Math.PI*2);ctx.fill();
    drawWhirlField(cx,cy,r,t,w);
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);ctx.clip();
    var ocean=ctx.createLinearGradient(cx-r,cy-r,cx+r,cy+r);
    ocean.addColorStop(0,'rgba(10,35,49,.2)');ocean.addColorStop(.6,'rgba(15,64,78,.2)');ocean.addColorStop(1,'rgba(3,13,22,.42)');
    ctx.fillStyle=ocean;ctx.fillRect(cx-r,cy-r,r*2,r*2);
    ctx.lineWidth=.7;ctx.strokeStyle='rgba(86,180,198,.18)';
    for(var lat=-60;lat<=60;lat+=20){
      var pts=[];for(var lon=-180;lon<=180;lon+=3)pts.push([lon,lat]);
      if(pathGeo(pts,rotation,cx,cy,r,false))ctx.stroke();
    }
    for(var lon=-180;lon<180;lon+=20){
      var m=[];for(var lat=-88;lat<=88;lat+=3)m.push([lon,lat]);
      if(pathGeo(m,rotation,cx,cy,r,false))ctx.stroke();
    }
    if(countryShapes.length){
      drawCountryGeometry(rotation,cx,cy,r,activeContinent,1.006,false,false);
    }else{
      ctx.fillStyle='rgba(91,175,183,.07)';ctx.strokeStyle='rgba(132,211,215,.30)';ctx.lineWidth=.8;
      for(var c=0;c<continents.length;c++){if(pathGeo(continents[c],rotation,cx,cy,r,true)){ctx.fill();ctx.stroke();}}
    }
    for(var tx=0;tx<globeTexture.length;tx++){
      var texture=globeTexture[tx];
      var texturePoint=project(texture[0],texture[1],rotation,cx,cy,r);
      if(texturePoint.z>.02){
        ctx.fillStyle='rgba(156,219,225,'+(texture[2]*texturePoint.z)+')';
        ctx.fillRect(texturePoint.x,texturePoint.y,texturePoint.z>0.7?1.4:.8,texturePoint.z>0.7?1.4:.8);
      }
    }
    var projectedHubs=[];
    for(var hubIndex=0;hubIndex<marketHubs.length;hubIndex++){
      projectedHubs.push(project(marketHubs[hubIndex].lon,marketHubs[hubIndex].lat,rotation,cx,cy,r));
    }
    ctx.setLineDash([2,5]);ctx.lineWidth=.7;
    for(var linkIndex=0;linkIndex<marketLinks.length;linkIndex++){
      var link=marketLinks[linkIndex],from=projectedHubs[link[0]],to=projectedHubs[link[1]];
      if(from.z>.04&&to.z>.04){
        var control={x:(from.x+to.x)/2,y:(from.y+to.y)/2-Math.min(28,Math.abs(to.x-from.x)*.16)};
        ctx.strokeStyle='rgba(84,198,216,.28)';
        ctx.beginPath();ctx.moveTo(from.x,from.y);ctx.quadraticCurveTo(control.x,control.y,to.x,to.y);ctx.stroke();
        var packetProgress=(t*.00018+linkIndex*.23)%1;
        var packet=quadraticPoint(from,control,to,packetProgress);
        ctx.fillStyle='rgba(213,180,93,.92)';ctx.beginPath();ctx.arc(packet.x,packet.y,1.55,0,Math.PI*2);ctx.fill();
      }
    }
    ctx.setLineDash([]);
    var globeBreath=.5+.5*Math.sin(t*.00048);
    var breathGlow=ctx.createRadialGradient(cx-r*.28,cy-r*.2,r*.03,cx-r*.08,cy-r*.06,r*.88);
    breathGlow.addColorStop(0,'rgba(119,211,220,'+(.07+globeBreath*.05)+')');
    breathGlow.addColorStop(.52,'rgba(46,129,147,'+(.025+globeBreath*.025)+')');
    breathGlow.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=breathGlow;ctx.fillRect(cx-r,cy-r,r*2,r*2);
    ctx.restore();
    drawDottedOrbit(cx,cy,r*1.1,-.19,.73,t,.2,'rgba(104,192,205,.42)');
    drawDottedOrbit(cx,cy,r*1.22,.55,.34,-t,1.8,'rgba(213,180,93,.30)');
    if(w>720)drawDottedOrbit(cx,cy,r*1.34,-.72,.22,t,3.4,'rgba(127,155,166,.26)');
    ctx.strokeStyle='rgba(126,205,218,.46)';ctx.lineWidth=1.15;ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);ctx.stroke();
    ctx.strokeStyle='rgba(213,180,93,.27)';ctx.beginPath();ctx.arc(cx,cy,r+10,Math.PI*.1,Math.PI*.46);ctx.stroke();
    ctx.beginPath();ctx.arc(cx,cy,r+10,Math.PI*1.1,Math.PI*1.34);ctx.stroke();
    if(activeScore>.08){
      ctx.shadowColor='rgba(84,198,216,.32)';ctx.shadowBlur=14;
      if(countryShapes.length){
        drawCountryGeometry(rotation,cx,cy,r,activeContinent,activeLift,false,true);
      }else{
        ctx.fillStyle='rgba(12,55,67,.28)';
        ctx.strokeStyle='rgba(126,213,222,.48)';
        ctx.lineWidth=1;
        if(pathGeo(continents[activeContinent],rotation,cx,cy,r*activeLift,true)){ctx.fill();ctx.stroke();}
      }
      ctx.shadowBlur=0;
    }
    var visibleTiles=[];
    for(var tileIndex=0;tileIndex<hexLandTiles.length;tileIndex++){
      var tile=hexLandTiles[tileIndex];
      var surfacePoint=project(tile.lon,tile.lat,rotation,cx,cy,r);
      if(surfacePoint.z>.015)visibleTiles.push({tile:tile,point:surfacePoint,index:tileIndex});
    }
    visibleTiles.sort(function(a,b){return a.point.z-b.point.z;});
    ctx.lineWidth=.55;
    for(var visibleIndex=0;visibleIndex<visibleTiles.length;visibleIndex++){
      var visibleTile=visibleTiles[visibleIndex],landTile=visibleTile.tile,landPoint=visibleTile.point;
      var continentProjection=centerProjections[landTile.continent];
      var continentFrontness=Math.max(0,Math.min(1,(continentProjection.z-.1)/.86));
      var focusWeight=Math.max(0,Math.min(1,(continentProjection.z-(activeScore-.18))/.18));
      var regionDetach=detachProgress*(.018*Math.pow(continentFrontness,2)+.132*Math.pow(focusWeight,2.3));
      var liftWave=(Math.sin(t*.00135+landTile.phase)+1)*.004;
      var lift=1+landTile.lift+liftWave+regionDetach;
      var elevatedX=cx+(landPoint.x-cx)*lift;
      var elevatedY=cy+(landPoint.y-cy)*lift;
      var tileSize=(2.05+landPoint.z*2.55)*(w<620?.78:1);
      var depthAlpha=.08+landPoint.z*.18;
      drawHexagon(landPoint.x,landPoint.y,tileSize*.9,.52,'rgba(8,28,37,'+(depthAlpha+.06)+')',null);
      if(regionDetach>.025){
        drawHexExtrusion(landPoint.x,landPoint.y,elevatedX,elevatedY,tileSize,.52,regionDetach*3.8);
      }else if(visibleTile.index%4===0){
        ctx.strokeStyle='rgba(87,180,195,'+(.08+landPoint.z*.12)+')';
        ctx.beginPath();ctx.moveTo(landPoint.x,landPoint.y);ctx.lineTo(elevatedX,elevatedY);ctx.stroke();
      }
      var pulse=.72+.28*Math.sin(t*.0017+landTile.phase);
      var tileAlpha=(.16+landPoint.z*.48+regionDetach*.72)*pulse;
      var tileFill=landTile.accent
        ?'rgba(213,180,93,'+Math.min(.9,tileAlpha+.18)+')'
        :'rgba(82,190,207,'+Math.min(.82,tileAlpha)+')';
      var tileStroke=landTile.accent
        ?'rgba(245,221,153,'+Math.min(.92,tileAlpha+.22)+')'
        :'rgba(166,226,232,'+Math.min(.78,tileAlpha+.12)+')';
      ctx.shadowColor=landTile.accent?'rgba(213,180,93,.55)':'rgba(84,198,216,.44)';
      ctx.shadowBlur=landTile.accent?8:5+regionDetach*22;
      drawHexagon(elevatedX,elevatedY,tileSize,.52,tileFill,tileStroke);
      ctx.shadowBlur=0;
    }
    if(countryShapes.length){
      drawCountryGeometry(rotation,cx,cy,r,activeContinent,activeLift,true,false);
    }
    drawWealthHud(t,w,h,cx,cy,r,centerProjections[activeContinent],activeLift,continentCenters[activeContinent].label);
    drawCapitalLights(t,w,rotation,cx,cy,r);
    for(var n=0;n<projectedHubs.length;n++){
      var np=projectedHubs[n];
      if(np.z>.08){
        var nodePulse=5+((t*.012+n*5)%12);
        ctx.fillStyle='rgba(213,180,93,.94)';ctx.beginPath();ctx.arc(np.x,np.y,2.2,0,Math.PI*2);ctx.fill();
        ctx.strokeStyle='rgba(213,180,93,'+(Math.max(.04,.32-(nodePulse-5)*.025))+')';
        ctx.beginPath();ctx.arc(np.x,np.y,nodePulse,0,Math.PI*2);ctx.stroke();
        if(w>900&&np.z>.55){
          ctx.fillStyle='rgba(190,211,218,.62)';ctx.font='600 7px ui-monospace,Consolas,monospace';
          ctx.fillText(marketHubs[n].label,np.x+8,np.y-7);
        }
      }
    }
    drawSatellite(cx,cy,r*1.16,t,-.28,.4,.43);
    if(w>720)drawSatellite(cx,cy,r*1.28,t*.82,.62,3.1,.28);
  }
  function drawMarket(t,w,h){
    var left=w*.31,right=w*.81,base=h*.83,top=h*.68;
    if(w<720){left=w*.08;right=w*.91;base=h*.58;top=h*.48;}
    ctx.strokeStyle='rgba(84,198,216,.10)';ctx.lineWidth=1;
    for(var y=0;y<4;y++){var gy=top+(base-top)*y/3;ctx.beginPath();ctx.moveTo(left,gy);ctx.lineTo(right,gy);ctx.stroke();}
    var values=[.72,.6,.66,.48,.55,.33,.4,.25,.31,.15,.22,.08];
    var visible=Math.min(values.length,Math.max(2,Math.floor((t/360)*values.length)));
    ctx.beginPath();
    for(var i=0;i<visible;i++){
      var x=left+(right-left)*i/(values.length-1);
      var yy=top+(base-top)*(values[i]+Math.sin(t*.0016+i*.8)*.012);
      if(!i)ctx.moveTo(x,yy);else ctx.lineTo(x,yy);
    }
    ctx.strokeStyle='rgba(84,198,216,.92)';ctx.lineWidth=1.8;ctx.shadowColor='rgba(84,198,216,.55)';ctx.shadowBlur=8;ctx.stroke();ctx.shadowBlur=0;
    var benchmark=[.79,.73,.68,.64,.58,.55,.49,.45,.39,.34,.3,.27];
    ctx.strokeStyle='rgba(213,180,93,.26)';ctx.lineWidth=1;ctx.beginPath();
    for(var benchmarkIndex=0;benchmarkIndex<benchmark.length;benchmarkIndex++){
      var benchmarkX=left+(right-left)*benchmarkIndex/(benchmark.length-1);
      var benchmarkY=top+(base-top)*(benchmark[benchmarkIndex]+Math.sin(t*.0011+benchmarkIndex)*.008);
      if(!benchmarkIndex)ctx.moveTo(benchmarkX,benchmarkY);else ctx.lineTo(benchmarkX,benchmarkY);
    }
    ctx.stroke();
    if(visible>1){
      var lx=left+(right-left)*(visible-1)/(values.length-1);
      var ly=top+(base-top)*(values[visible-1]+Math.sin(t*.0016+(visible-1)*.8)*.012);
      var marketPulse=4+((t*.018)%15);
      ctx.fillStyle='#d5b45d';ctx.beginPath();ctx.arc(lx,ly,2.6,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle='rgba(84,198,216,'+(Math.max(.03,.34-(marketPulse-4)*.02))+')';
      ctx.beginPath();ctx.arc(lx,ly,marketPulse,0,Math.PI*2);ctx.stroke();
    }
    var bx=right+18,bw=5,gap=5,bars=[.38,.67,.48,.82,.59,.92,.71];
    if(w>720){
      for(var b=0;b<bars.length;b++){
        var barEnergy=.86+Math.sin(t*.0018+b*.9)*.14;
        var bh=(base-top)*bars[b]*barEnergy;
        ctx.fillStyle=b===bars.length-1?'rgba(213,180,93,.72)':'rgba(84,198,216,.28)';
        ctx.fillRect(bx+b*(bw+gap),base-bh,bw,bh);
      }
    }
  }
  function draw(now){
    if(done||!ctx)return;
    var w=innerWidth,h=innerHeight,rawTime=reduce?6000:now-start,t=cinematicTime(rawTime);
    ctx.clearRect(0,0,w,h);
    var bg=ctx.createLinearGradient(0,0,w,h);
    bg.addColorStop(0,'#050b14');bg.addColorStop(.5,'#06101b');bg.addColorStop(1,'#02050a');
    ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);
    drawFinanceBackdrop(t,w,h);
    drawStrategyBackdrop(t,w,h);
    drawGlobe(t,w,h);drawMarket(t,w,h);
    if(!reduce)raf=requestAnimationFrame(draw);
  }
  function updateClock(){
    if(!clockEl)return;
    var d=new Date(),p=function(v){return String(v).padStart(2,'0');};
    clockEl.textContent='ZURICH '+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
  }
  intro.addEventListener('click',finish);
  window.addEventListener('keydown',handleKey);
  window.addEventListener('resize',resize);
  calmTimer=setTimeout(function(){if(!done)intro.classList.add('intro-calm');},2600);
  resize();updateClock();clockTimer=setInterval(updateClock,1000);draw(performance.now());
  if(reduce){
    if(logEl)logEl.textContent='System wird vorbereitet';
    if(bar)bar.style.width='20%';
    setTimeout(markReady,6000);
    return;
  }
  var i=0;
  (function tick(){
    if(done)return;
    if(i<steps.length){
      if(logEl)logEl.textContent=steps[i];
      if(bar)bar.style.width=Math.round((i+1)/steps.length*96)+'%';
      i++;setTimeout(tick,1200);
    }else markReady();
  })();
  setTimeout(markReady,6000);
})();

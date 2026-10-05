import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
const root=process.argv[2];
const durationLimit=Number(process.argv[3]);
if(!root || !Number.isFinite(durationLimit) || durationLimit<1 || durationLimit>43200)throw Error('Use: node fetch-vod-segments.mjs PRIVATE_DIRECTORY SECONDS');
const base=(await fs.readFile(root+'/source-url-private.txt','utf8')).trim();
const text=await fs.readFile(root+'/source-playlist-private.m3u8','utf8');
if(text.includes('#EXT-X-KEY') || text.includes('#EXT-X-DISCONTINUITY') || text.includes('#EXT-X-BYTERANGE'))throw Error('Encrypted media unsupported by this collector');
const segments=[];let duration=null,at=0;
for(const line of text.split('\n').map(v=>v.trim())){
 if(line.startsWith('#EXTINF:'))duration=Number(line.slice(8).split(',')[0]);
 else if(line && !line.startsWith('#') && duration!==null){
  if(at<durationLimit)segments.push({url:new URL(line,base).href,duration,start:at,index:segments.length});
  at+=duration;duration=null;
 }
}
if(!segments.length || at<durationLimit)throw Error('Source shorter than requested duration');
const dir=root+'/segments';await fs.mkdir(dir,{recursive:true});
let next=0,done=0,bytes=0;const start=Date.now();const failures=[];
async function worker(){while(next<segments.length){const seg=segments[next++];const file=path.join(dir,String(seg.index).padStart(5,'0')+'.ts');
 try {const s=await fs.stat(file);if(s.size>188){const b=await fs.readFile(file);seg.sha256=crypto.createHash('sha256').update(b).digest('hex');seg.bytes=s.size;done++;bytes+=s.size;continue;}}catch{}
 let last;
 for(let retry=0;retry<3;retry++)try{
  const res=await fetch(seg.url,{signal:AbortSignal.timeout(60000)});if(!res.ok)throw Error('HTTP '+res.status);
  const b=Buffer.from(await res.arrayBuffer());if(b.length<188)throw Error('empty segment');
  await fs.writeFile(file+'.part',b);await fs.rename(file+'.part',file);seg.bytes=b.length;seg.sha256=crypto.createHash('sha256').update(b).digest('hex');bytes+=b.length;done++;last=null;break;
 }catch(e){last=String(e);await new Promise(r=>setTimeout(r,1000*(retry+1)));}
 if(last)failures.push({index:seg.index,error:last});
 if(done%100===0){const p={done,total:segments.length,bytes,elapsed_seconds:(Date.now()-start)/1000,failures:failures.length};await fs.writeFile(root+'/download-progress.json',JSON.stringify(p));console.log(JSON.stringify(p));}
}}
await Promise.all(Array.from({length:8},worker));
await fs.writeFile(root+'/segments-manifest-private.json',JSON.stringify({segments,failures},null,2));
if(failures.length)throw Error('Incomplete segment download: '+failures.length);
let playlist='#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:'+Math.ceil(Math.max(...segments.map(s=>s.duration)))+'\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MEDIA-SEQUENCE:0\n';
for(const seg of segments)playlist+=`#EXTINF:${seg.duration},\nsegments/${String(seg.index).padStart(5,'0')}.ts\n`;
playlist+='#EXT-X-ENDLIST\n';await fs.writeFile(root+'/local.m3u8',playlist);
console.log(JSON.stringify({complete:true,segments:segments.length,bytes,seconds:segments.reduce((a,b)=>a+b.duration,0),elapsed_seconds:(Date.now()-start)/1000}));

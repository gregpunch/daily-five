#!/usr/bin/env python3
"""Max Edge clip assembler.
Usage: python3 video/assemble.py 2026-10-26 [--segdir video/work/2026-10-26] [--skip-stt-gate]
Inputs: <segdir>/seg1.mp4 .. seg4.mp4 (≈15 s vertical talking-head segments made from
video/host-max-edge.jpg + video/script-<date>.json lines).
Steps: speech-to-text check (faster-whisper) vs the script, trim dead air to the first/last
spoken word, alternating slow zoom, teal banner + whoosh at each join, burned word-timed
captions, quiet synthesized music bed, readdailyfive.com end card.
Outputs: video/max-<date>.mp4 (720x1280), clips/max-<date>.mp4 (compressed 540x960),
clips/max-<date>.jpg (poster), video/work/<date>/stt-report.json.
"""
import json, os, re, subprocess, sys, difflib, math
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
D=sys.argv[1]
SEG=os.path.join(HERE,'work',D)
if '--segdir' in sys.argv: SEG=os.path.abspath(sys.argv[sys.argv.index('--segdir')+1])
GATE='--skip-stt-gate' not in sys.argv
S=json.load(open(os.path.join(HERE,f'script-{D}.json')))
W,H,FPS=720,1280,24
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
TEAL='0x14C8B4'
OUT=os.path.join(SEG,'build'); os.makedirs(OUT,exist_ok=True)
def run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode: print(' '.join(cmd)); print(r.stderr[-3000:]); sys.exit(1)
    return r.stdout
def dur(f): return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f]).strip())
def norm(t):
    t=t.lower().replace('a.i.','ai').replace('½',' and a half')
    return re.findall(r"[a-z0-9']+",t)
# ---------- 1. STT ----------
from faster_whisper import WhisperModel
model=WhisperModel(os.environ.get('WHISPER_MODEL','small.en'),device='cpu',compute_type='int8')
report=[]; segs=[]
for s in S['segments']:
    f=os.path.join(SEG,f"seg{s['id']}.mp4")
    wav=os.path.join(OUT,f"seg{s['id']}.wav")
    run(['ffmpeg','-v','error','-y','-i',f,'-ac','1','-ar','16000',wav])
    import wave, numpy as np
    with wave.open(wav) as wf: pcm=np.frombuffer(wf.readframes(wf.getnframes()),np.int16).astype(np.float32)/32768
    res,_=model.transcribe(pcm,word_timestamps=True,vad_filter=False,initial_prompt='Max Edge, The Daily Five, Sixers, Polymarket, T-Mobile, Verizon, readdailyfive.com')
    words=[w for r in res for w in r.words]
    heard=' '.join(w.word.strip() for w in words)
    a,b=norm(s['line']),norm(heard)
    ratio=difflib.SequenceMatcher(None,a,b).ratio()
    missing=[x for x in a if x not in b]
    report.append({'seg':s['id'],'expected':s['line'],'heard':heard,'match':round(ratio,3),'missing_words':missing})
    print(f"seg{s['id']}: match {ratio:.2f}  heard: {heard}")
    if not words: print('no speech found'); sys.exit(1)
    t0=max(0,words[0].start-0.10); t1=min(dur(f),words[-1].end+0.22)
    segs.append((s,f,t0,t1,words))
json.dump(report,open(os.path.join(SEG,'stt-report.json'),'w'),indent=1)
bad=[r for r in report if r['match']<0.85]
if bad and GATE: print('STT mismatch (<0.85) on segs',[r['seg'] for r in bad],'- regenerate or pass --skip-stt-gate'); sys.exit(2)
# ---------- 2. captions (ASS, word timed, 3-4 word chunks) ----------
def ts(x): h=int(x//3600); m=int(x%3600//60); s=x%60; return f"{h}:{m:02d}:{s:05.2f}"
ass=["[Script Info]","ScriptType: v4.00+",f"PlayResX: {W}",f"PlayResY: {H}","",
 "[V4+ Styles]","Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
 "Style: Cap,DejaVu Sans,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,5,2,2,60,60,330,1","",
 "[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
off=0.0; parts=[]
for i,(s,f,t0,t1,words) in enumerate(segs):
    ws=[w for w in words if w.end>t0 and w.start<t1]
    chunk=[]
    def flush(chunk):
        if not chunk: return
        a=off+chunk[0].start-t0; b=off+chunk[-1].end-t0+0.08
        txt=' '.join(w.word.strip() for w in chunk).replace('A.I.','AI')
        txt=re.sub(r' (?=[.\-]\w)','',txt).replace('Phillies priced',"Philly's priced")
        ass.append(f"Dialogue: 0,{ts(max(a,off))},{ts(b)},Cap,,0,0,0,,{txt}")
    for w in ws:
        chunk.append(w)
        if len(chunk)>=4 or re.search(r'[.?!,]$',w.word.strip()) and len(chunk)>=2: flush(chunk); chunk=[]
    flush(chunk)
    parts.append((s,f,t0,t1,off)); off+=t1-t0
TOTAL_TALK=off
open(os.path.join(OUT,'caps.ass'),'w').write('\n'.join(ass)+'\n')
# ---------- 3. per-segment video: trim, alternating zoom, teal banner ----------
def esc(t): return t.replace('\\','\\\\').replace(':','\\:').replace("'","\u2019")
vids=[]
for i,(s,f,t0,t1,o) in enumerate(parts):
    d=t1-t0; n=int(d*FPS)+1
    z=f"1+0.07*on/{n}" if i%2==0 else f"1.07-0.07*on/{n}"
    vf=(f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
        f"drawbox=x=0:y=70:w='if(lt(t,1.8),{W}*min(1,t/0.25),0)':h=78:color={TEAL}@0.92:t=fill:enable='lt(t,1.8)',"
        f"drawtext=fontfile={FONT}:text='{esc(s['banner'])}':fontcolor=0x07080d:fontsize=40:x=28:y=91:enable='between(t,0.2,1.8)'")
    out=os.path.join(OUT,f'v{i+1}.mp4')
    run(['ffmpeg','-v','error','-y','-ss',f'{t0:.3f}','-t',f'{d:.3f}','-i',f,'-vf',vf,'-af','aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11','-ac','2',
         '-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',out])
    vids.append(out)
# ---------- 4. end card ----------
host=os.path.join(HERE,'host-max-edge.jpg'); ec=os.path.join(OUT,'end.mp4'); EC=2.6
run(['ffmpeg','-v','error','-y','-loop','1','-t',str(EC),'-i',host,'-f','lavfi','-t',str(EC),'-i','anullsrc=r=48000:cl=stereo','-vf',
     f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=8:2,eq=brightness=-0.25,"
     f"drawbox=x=0:y=560:w={W}:h=190:color={TEAL}@0.95:t=fill,"
     f"drawtext=fontfile={FONT}:text='{esc(S['end_card']['title'])}':fontcolor=0x07080d:fontsize=64:x=(w-tw)/2:y=600,"
     f"drawtext=fontfile={FONT}:text='{esc(S['end_card']['sub'])}':fontcolor=0x07080d:fontsize=28:x=(w-tw)/2:y=690,"
     f"drawtext=fontfile={FONT}:text='Max Edge is an AI host · Not financial advice · 21+':fontcolor=white:fontsize=24:x=(w-tw)/2:y=820,fps={FPS}",
     '-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest',ec])
vids.append(ec)
# ---------- 5. concat + captions + whoosh + music ----------
lst=os.path.join(OUT,'list.txt'); open(lst,'w').write(''.join(f"file '{v}'\n" for v in vids))
cat=os.path.join(OUT,'cat.mp4')
run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',lst,'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',cat])
T=dur(cat)
joins=[o for (_,_,_,_,o) in parts[1:]]+[TOTAL_TALK]
# whoosh: band-passed noise with a quick swell, ~0.45 s, centred just before each join
wh=os.path.join(OUT,'whoosh.wav')
run(['ffmpeg','-v','error','-y','-f','lavfi','-i','anoisesrc=d=0.5:c=pink:r=48000:a=0.9','-af',
     "highpass=f=400,lowpass=f=5000,volume='0.9*sin(PI*t/0.5)':eval=frame,afade=t=out:st=0.35:d=0.15",'-ac','2',wh])
# music bed: soft A-minor pad with gentle pulse
mb=os.path.join(OUT,'music.wav')
pad="0.20*sin(2*PI*220*t)+0.14*sin(2*PI*261.63*t)+0.14*sin(2*PI*329.63*t)+0.08*sin(2*PI*110*t)"
run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f"aevalsrc='({pad})*(0.75+0.25*sin(2*PI*2*t))':s=48000:d={T:.2f}",'-af',
     f"lowpass=f=1800,afade=t=in:d=1,afade=t=out:st={T-1.5:.2f}:d=1.5,volume=0.11",'-ac','2',mb])
inputs=['-i',cat,'-i',mb]+sum([['-i',wh] for _ in joins],[])
fc=[f"[0:v]subtitles={os.path.join(OUT,'caps.ass')}[v]"]
mix=['[0:a]','[1:a]']
for k,j in enumerate(joins):
    ms=int(max(0,j-0.3)*1000); fc.append(f"[{k+2}:a]volume=0.55,adelay={ms}|{ms}[w{k}]"); mix.append(f'[w{k}]')
fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[a]")
final=os.path.join(HERE,f'max-{D}.mp4')
run(['ffmpeg','-v','error','-y']+inputs+['-filter_complex',';'.join(fc),'-map','[v]','-map','[a]','-c:v','libx264','-preset','slow','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',final])
clip=os.path.join(ROOT,'clips',f'max-{D}.mp4'); poster=os.path.join(ROOT,'clips',f'max-{D}.jpg')
os.makedirs(os.path.dirname(clip),exist_ok=True)
run(['ffmpeg','-v','error','-y','-i',final,'-vf','scale=540:960','-c:v','libx264','-preset','slow','-crf','27','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k','-movflags','+faststart',clip])
run(['ffmpeg','-v','error','-y','-ss','1.0','-i',final,'-frames:v','1','-vf','scale=540:960','-q:v','3',poster])
print(f"final {final} {dur(final):.1f}s; clip {clip} {os.path.getsize(clip)/1e6:.1f} MB; poster {poster}")

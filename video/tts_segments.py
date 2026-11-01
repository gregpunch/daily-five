#!/usr/bin/env python3
"""Fallback Max Edge segments when AI video generation fails (no seg*.mp4 in video/work/<date>/).
Usage: python3 video/tts_segments.py 2026-11-01 [--force]
Makes seg1..seg4.mp4 from video/host-max-edge.jpg + an offline Piper TTS voice (no account, no cost)
reading each script line, with a teal live voice waveform and a 'MAX EDGE · AI HOST' label.
Then run: python3 video/assemble.py <date>  (STT gate, banners, captions, music, end card as usual).
Deps: pip install --break-system-packages piper-tts ; voice files are fetched once into ~/.cache/piper.
"""
import json, os, subprocess, sys, wave, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__)); D=sys.argv[1]
SEG=os.path.join(HERE,'work',D); os.makedirs(SEG,exist_ok=True)
VOICE=os.environ.get('MAX_VOICE','en_US-ryan-high'); SPEED=float(os.environ.get('MAX_SPEED','1.0'))
CACHE=os.path.expanduser('~/.cache/piper'); os.makedirs(CACHE,exist_ok=True)
onnx=os.path.join(CACHE,VOICE+'.onnx')
if not os.path.exists(onnx):
    lang,name,q=VOICE.split('-'); base=f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang[:2]}/{lang}/{name}/{q}/{VOICE}.onnx"
    for ext in ('','.json'): urllib.request.urlretrieve(base+ext,onnx+ext)
from piper import PiperVoice
from piper.config import SynthesisConfig
v=PiperVoice.load(onnx); cfg=SynthesisConfig(length_scale=SPEED,noise_scale=0.75,noise_w_scale=0.9)
S=json.load(open(os.path.join(HERE,f'script-{D}.json')))
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'; host=os.path.join(HERE,'host-max-edge.jpg')
for s in S['segments']:
    out=os.path.join(SEG,f"seg{s['id']}.mp4")
    if os.path.exists(out) and '--force' not in sys.argv: print('keep',out); continue
    wav=os.path.join(SEG,f"tts{s['id']}.wav")
    with wave.open(wav,'wb') as wf: v.synthesize_wav(s['line'],wf,syn_config=cfg)
    fc=("[1:a]asplit[a1][a2];[a1]aformat=channel_layouts=mono,volume=4,showwaves=s=520x110:mode=p2p:draw=full:rate=24:colors=0x14C8B4,format=rgba[w];"
        "[0:v]scale=720:1280,drawbox=x=90:y=1035:w=540:h=120:color=black@0.45:t=fill,format=yuv420p[b];"
        f"[b][w]overlay=100:1040:shortest=1,drawtext=fontfile={FONT}:text='MAX EDGE · AI HOST':fontcolor=0x14C8B4:fontsize=26:x=(w-tw)/2:y=1165,format=yuv420p[v]")
    r=subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-framerate','24','-i',host,'-i',wav,'-filter_complex',fc,'-map','[v]','-map','[a2]',
                      '-shortest','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','160k',out],capture_output=True,text=True)
    if r.returncode: print(r.stderr[-2000:]); sys.exit(1)
    print('made',out)

import os, subprocess, warnings
warnings.filterwarnings("ignore")
import numpy as np, librosa
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT,"llama.cpp","build","bin","llama-tts.exe")
M  = os.path.join(ROOT,"models","Qwen3-TTS-0.6B-f16.gguf")
MM = os.path.join(ROOT,"models","mmproj-Qwen3-TTS-0.6B-f16.gguf")
OUT= os.path.join(ROOT,"ctest","voice_ab","refcand"); os.makedirs(OUT,exist_ok=True)
XY   = os.path.join(ROOT,"ctest","voice_ab","refs","ref_xy_one.wav")
BOOT = os.path.join(ROOT,"ctest","voice_ab","refs","ref_spk1_p3.wav")
SPK1 = os.path.join(ROOT,"models","speaker_refs","spk_1.wav")
def synth(t, ref, name, seed=1):
    d=os.path.join(OUT,name+".wav")
    c=[BIN,"-m",M,"-mm",MM,"--tts-lang","zh","-t","12","-n","96","-s",str(seed),"-o",d,"-p",t]
    if ref: c+=["--tts-speaker-file",ref]
    subprocess.run(c,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return d
def f0(p):
    y,sr=librosa.load(p,sr=None)
    f,v,_=librosa.pyin(y,fmin=80,fmax=600,sr=sr); f=f[v]; f=f[~np.isnan(f)]
    return float(np.median(f)) if len(f) else float("nan")
T=["你好呀，今天过得怎么样？","我不太清楚诶，你再问问别人吧。","诶，你又来啦，我还以为你把我忘了。"]
print("=== 固定 seed=1，换文本：是不是同一个人？（听） ===")
for lbl,ref in (("Xiaoyi",XY),("自举boot",BOOT)):
    vs=[]
    for i,t in enumerate(T):
        p=synth(t,ref,f"fixseed_{'xy' if ref==XY else 'boot'}_{i}",seed=1)
        vs.append(f0(p))
    print(f"  {lbl:10} 三句 F0 = "+" ".join(f"{v:.0f}" for v in vs)+f"   极差 {max(vs)-min(vs):.0f} Hz")
print("=== 自举参考的稳定性（同文本换 seed）===")
vs=[f0(synth(T[0],BOOT,f"bootstab_s{s}",seed=s)) for s in (1,2,3)]
print("  boot seed1/2/3 = "+" ".join(f"{v:.0f}" for v in vs)+f"   极差 {max(vs)-min(vs):.0f} Hz")

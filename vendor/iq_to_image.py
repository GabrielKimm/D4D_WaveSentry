"""HackRF IQ 녹음(.cs8) → 20 ms 스펙트로그램 그림(640×640 회색 PNG).

모델을 학습·평가할 때와 **똑같은 방식**으로 그림을 만든다. 이 방식이 조금이라도 다르면 모델 성능이 무너지므로 고치지 말 것.
  1) 녹음을 20 ms(400,000 표본)씩 겹치지 않게 자른다. 끝에 20 ms 가 안 되는 나머지는 버린다.
  2) 20 ms 의 평균을 빼고(가운데 줄 줄이기) 8,192점 푸리에 변환(한 칸 4,081 표본씩 이동)으로 세기(dB)를 구한다.
  3) 0 Hz ±100 kHz 줄들(HackRF 의 가운데 밝은 줄)을 같은 쪽 바로 바깥 줄의 값으로 같은 시각 그대로 채운다.
  4) 그림마다 가장 어두운 1 %를 검정, 가장 밝은 0.5 %를 흰색으로 늘려 0~255 로 바꾸고, 위가 높은 주파수가 되게 뒤집어 640×640 으로 줄인다.
  가로 = 시간 0~20 ms(왼쪽→오른쪽), 세로 = 중심 주파수 −10 MHz(아래) ~ +10 MHz(위).

입력: .cs8 또는 SigMF(iq.sigmf-data, int8) 파일 하나 또는 폴더(안을 모두 찾음, 이름이 _ 로 시작하는 폴더는 건너뜀).
      SigMF 는 옆의 iq.sigmf-meta 에서, .cs8 는 파일 옆의 <파일>.json(HackRF 수집 도구가 만든 것)에서 중심 주파수·샘플링 속도를 읽고,
      없으면 파일 이름의 "<숫자>Hz_<숫자>sps" 에서 읽는다. 둘 다 없으면 --fc, --fs 로 준다.
      **샘플링 속도는 20 MS/s 여야 한다**(모델이 세로 20 MHz 그림만 배웠음). 다르면 멈춘다.
출력: <out>/<입력 폴더 이름>/<녹음 이름>_f00.png … (1초 녹음 = 50장), <out>/index.csv(그림마다 원본 파일, 몇 번째 20 ms, 시각, 중심 주파수)

원본 코드: d4d/src/synth_iq.py 의 spectrogram_v7·to_gray_v7, d4d/src/spectrogram.py 의 spectrogram_db·to_image (같은 결과인지 픽셀 단위로 확인함, README 참고).
사용: python src/iq_to_image.py --input input --out work/images"""
import argparse, csv, json, re, sys, time
from pathlib import Path
import numpy as np
from scipy.signal import stft
from PIL import Image

FS = 20e6                       # 샘플링 속도(초당 복소 표본 수). 모델은 이 값의 그림만 배웠다
WIN = 0.02                      # 그림 한 장 = 20 ms
N = int(FS * WIN)               # 400,000 표본
NFFT, HOP = 8192, int(FS * 0.1 / 490)   # 푸리에 변환 길이 8,192, 이동 4,081 표본(시간 칸 약 204 µs, 그림 한 장 97칸)
DC_HALF = 100e3                 # 가운데 줄 지우기 폭 ±100 kHz
PX = 640                        # 그림 크기 640 × 640


def spectrogram_db(iq, fs=FS, nfft=NFFT, hop=HOP):
    """세기(dB)[주파수, 시간], 주파수(Hz, 중심 0 기준, 오름차순)."""
    f, t, Z = stft(iq, fs=fs, nperseg=nfft, noverlap=nfft - hop, window="hann", return_onesided=False, boundary=None, padded=False)
    f = np.fft.fftshift(f); Z = np.fft.fftshift(Z, axes=0)
    return (20 * np.log10(np.abs(Z) + 1e-12)).astype(np.float32), f


def spectrogram_clean(x):
    """평균을 빼고 스펙트로그램을 만든 뒤 0 Hz ±100 kHz 줄을 같은 쪽 바깥 줄로 채운다."""
    y = np.asarray(x, dtype=np.complex64); y = y - y.mean()
    S, f = spectrogram_db(y); k0 = int(np.argmin(np.abs(f))); K = int(np.ceil(DC_HALF / (FS / NFFT)))
    S = S.copy()
    for d in range(-K + 1, K):
        S[k0 + d] = S[k0 + (d + K if d >= 0 else d - K)]
    return S


def to_image(S_db, size=(PX, PX), p_lo=1.0, p_hi=99.5):
    """그림마다 가장 어두운 1 % → 검정, 가장 밝은 0.5 % → 흰색. 위가 높은 주파수, 왼쪽이 시작 시각."""
    lo, hi = np.percentile(S_db, [p_lo, p_hi])
    g = np.clip((S_db - lo) / max(hi - lo, 1e-6), 0, 1)
    return Image.fromarray((g[::-1] * 255).astype(np.uint8)).resize(size, Image.BILINEAR)


def picture(x):
    """20 ms IQ(복소수 400,000개) → 640×640 회색 그림(PIL)."""
    return to_image(spectrogram_clean(x))


def read_cs8(path):
    """HackRF .cs8: 헤더 없는 int8, I0,Q0,I1,Q1,… → complex64(크기 조절 없음, 학습 때와 같음)."""
    r = np.fromfile(path, dtype=np.int8).astype(np.float32)
    return (r[0::2] + 1j * r[1::2]).astype(np.complex64)


def meta_of(path, fc_arg, fs_arg):
    """중심 주파수·샘플링 속도: SigMF 면 옆의 .sigmf-meta → 옆의 .json → 파일 이름 → 명령 인자 순서로 찾는다."""
    if path.suffix == ".sigmf-data":   # 10-09: SDRangel 이 저장한 SigMF (iq.sigmf-data + iq.sigmf-meta)
        m = json.load(open(path.with_suffix(".sigmf-meta"), encoding="utf-8-sig")); g_ = m.get("global", {}); caps = m.get("captures", [{}])
        if not str(g_.get("core:datatype", "")).startswith("ci8"): sys.exit(f"[멈춤] {path}: 형식 {g_.get('core:datatype')} — int8 I/Q(ci8)만 읽을 수 있음")
        if len({c.get("core:frequency") for c in caps}) > 1: sys.exit(f"[멈춤] {path}: 녹음 중간에 중심 주파수가 바뀜(captures {len(caps)}개)")
        return float(caps[0]["core:frequency"]), float(g_["core:sample_rate"]), "sigmf-meta"
    j = Path(str(path) + ".json")
    if j.exists():
        m = json.load(open(j, encoding="utf-8-sig"))
        if "centerFrequencyHz" in m and "sampleRateHz" in m: return float(m["centerFrequencyHz"]), float(m["sampleRateHz"]), "json"
    g = re.search(r"(\d+)Hz_(\d+)sps", path.name)
    if g: return float(g.group(1)), float(g.group(2)), "file name"
    if fc_arg and fs_arg: return fc_arg, fs_arg, "argument"
    sys.exit(f"[멈춤] {path}: 중심 주파수·샘플링 속도를 알 수 없음. --fc 2450e6 --fs 20e6 처럼 주세요.")


def main():
    ap = argparse.ArgumentParser(description="HackRF .cs8 → 20 ms 스펙트로그램 그림(640×640 PNG)")
    ap.add_argument("--input", default="input", help=".cs8 파일 또는 폴더(안을 모두 찾음). 기본 input")
    ap.add_argument("--out", default="work/images", help="그림을 쌓을 폴더. 기본 work/images")
    ap.add_argument("--fc", type=float, default=None, help="중심 주파수(Hz). .json·파일 이름에 없을 때만")
    ap.add_argument("--fs", type=float, default=None, help="샘플링 속도(Hz). .json·파일 이름에 없을 때만. 20e6 이어야 함")
    ap.add_argument("--max_frames", type=int, default=0, help="녹음마다 앞에서부터 이 장수만 만듦(0 = 전부). 빨리 시험할 때")
    a = ap.parse_args()
    src = Path(a.input); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    # .cs8 와 SigMF(.sigmf-data). 이름이 _ 로 시작하는 폴더(예: _excluded, 학습에서 뺄 녹음) 아래는 건너뜀
    files = [src] if src.is_file() else sorted(f for pat in ("*.cs8", "*.sigmf-data") for f in src.rglob(pat)
                                                if not any(q.startswith("_") for q in f.relative_to(src).parts[:-1]))
    if not files: sys.exit(f"[멈춤] {src} 에 .cs8 또는 .sigmf-data 녹음이 없음")
    rows, t0 = [], time.time()
    for f in files:
        fc, fs, how = meta_of(f, a.fc, a.fs)
        if abs(fs - FS) > 1:
            sys.exit(f"[멈춤] {f.name}: 샘플링 속도 {fs / 1e6:g} MS/s. 이 모델은 20 MS/s 녹음만 쓸 수 있음(HackRF 를 -s 20000000 으로 녹음)")
        x = read_cs8(f); n_all = len(x) // N; n = min(n_all, a.max_frames) if a.max_frames else n_all
        top = f.relative_to(src).parts[0] if src.is_dir() and len(f.relative_to(src).parts) > 1 else f.parent.name
        d = out / top; d.mkdir(parents=True, exist_ok=True)
        stem = f.parent.name if f.suffix == ".sigmf-data" else f.stem   # SigMF 는 파일 이름이 모두 iq 라 녹음 폴더 이름을 씀
        wd = max(2, len(str(n_all - 1)))                                  # 녹음 전체 길이 기준: 1초 녹음은 f00~f49 그대로, 길면 f000~ (이름순 = 시간순)
        for i in range(n):
            name = f"{stem}_f{i:0{wd}d}.png"; picture(x[i * N:(i + 1) * N]).save(d / name)
            rows.append(dict(image=f"{top}/{name}", source=str(f), frame=i, t_start_ms=round(i * WIN * 1e3, 3), t_end_ms=round((i + 1) * WIN * 1e3, 3), fc_hz=int(fc), fs_hz=int(fs)))
        print(f"{f.name}: {len(x) / fs:.3f} 초 → 그림 {n}장 (중심 {fc / 1e6:g} MHz, 정보 출처 {how})", flush=True)
    idx = out / "index.csv"; old = []
    if idx.exists():   # 이미 있는 목록에 덧붙이되, 같은 그림은 새 값으로
        new = {r["image"] for r in rows}; old = [r for r in csv.DictReader(open(idx, encoding="utf-8")) if r["image"] not in new]
    with open(idx, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["image", "source", "frame", "t_start_ms", "t_end_ms", "fc_hz", "fs_hz"]); w.writeheader(); w.writerows(old + rows)
    print(f"끝: 그림 {len(rows)}장 → {out}/ ({time.time() - t0:.1f} 초, 그림 한 장 {1e3 * (time.time() - t0) / max(len(rows), 1):.0f} ms). 목록 {idx}")


if __name__ == "__main__":
    main()

"""Keep one verified CosyVoice model loaded while local speech is in use."""

from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import select
import signal
import sys
from tempfile import NamedTemporaryFile
from time import perf_counter
from unittest.mock import patch


def verify_local_package(package):
    from feiyu_runtime.common import checked_path, load, verify_package

    index = package / 'files_sha256.json'
    receipt = package.parent / f'.{package.name}.wallpaper-verified.json'

    def fingerprint():
        result = {}
        for name in ('files_sha256.json', *load(index)):
            entry = checked_path(package, name).stat()
            result[name] = [entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns, entry.st_ctime_ns]
        return result

    before = fingerprint()
    try:
        if load(receipt) == before:
            return load(package / 'manifest.json')
    except (OSError, ValueError):
        pass

    manifest = verify_package(package)
    if fingerprint() != before:
        raise ValueError('Model files changed during verification')
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=receipt.parent, delete=False) as temporary:
        json.dump(before, temporary)
    Path(temporary.name).replace(receipt)
    return manifest


def load_voice(grammars, server, package, profile_path):
    started = perf_counter()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', OMP_NUM_THREADS='4')
    sys.path.insert(0, str(server))
    from feiyu_runtime.common import (apply_backend_env, checked_path, cpu_onnx_sessions, load,
                                      prepare, verify_audio_library, verify_repo)

    profile = load(profile_path)
    manifest = verify_local_package(package)
    print(f'Model integrity: {perf_counter() - started:.2f}s', file=sys.stderr)
    repo = verify_repo(profile)
    apply_backend_env(profile)
    os.chdir(repo)
    sys.path[:0] = [str(repo), str(repo / 'third_party/Matcha-TTS')]
    import wetext.wetext

    def local_grammars(model_id):
        if model_id != 'pengzhendong/wetext':
            raise ValueError('Unexpected text grammar model')
        for language in ('zh', 'en'):
            for filename in ('tagger.fst', 'verbalizer.fst'):
                if not (grammars / language / 'tn' / filename).is_file():
                    raise FileNotFoundError('Local WeText grammar is missing')
        return str(grammars)

    wetext.wetext.snapshot_download = local_grammars
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    import torch
    from cosyvoice.cli.cosyvoice import CosyVoice3
    from cosyvoice.cli.model import CosyVoice3Model
    from cosyvoice.utils.common import set_all_random_seed

    prepare(torch, profile)
    verify_audio_library(profile)
    style = manifest['styles']['cute']
    checkpoint = checked_path(package, style['llm_checkpoint'])
    reference = checked_path(package, style['reference_audio'])
    params = manifest['inference']
    prompt = params['prompt_prefix'] + style['reference_text']
    load_weights = CosyVoice3Model.load

    def load_cute_weights(model, _base_checkpoint, flow, hift):
        return load_weights(model, str(checkpoint), flow, hift)

    with patch.object(CosyVoice3Model, 'load', load_cute_weights), cpu_onnx_sessions(ort, []):
        voice = CosyVoice3(model_dir=str(checked_path(package, manifest['base_model_dir'])),
                           fp16=False, load_trt=False, load_vllm=False)
    speaker = 'feiyu-cute'
    with torch.inference_mode():
        voice.add_zero_shot_spk(prompt, str(reference), speaker)
    print(f'Model and reference ready: {perf_counter() - started:.2f}s', file=sys.stderr)

    def synthesize(text, path):
        set_all_random_seed(params['seed'])
        with torch.inference_mode():
            chunks = [part['tts_speech'].detach().cpu().numpy()[0]
                      for part in voice.inference_zero_shot(text, prompt, str(reference),
                                                           zero_shot_spk_id=speaker, speed=params['speed'])]
        if not chunks:
            raise ValueError('TTS returned no audio')
        samples = np.concatenate(chunks)
        peak = float(np.abs(samples).max())
        if len(samples) <= 2400 or not np.isfinite(samples).all() or peak <= 1e-4:
            raise ValueError('Invalid TTS audio')
        sf.write(path, samples * min(1., .98 / peak), voice.sample_rate, subtype='PCM_16')

    return synthesize


def main():
    _, grammar_dir, server, package, profile_path = sys.argv
    reply_stream = sys.stdout
    synthesize = None
    with redirect_stdout(sys.stderr):
        while select.select([sys.stdin], [], [], 45)[0]:
            line = sys.stdin.readline()
            if not line:
                break
            signal.alarm(115)
            request = json.loads(line)
            if synthesize is None:
                synthesize = load_voice(*map(Path, (grammar_dir, server, package, profile_path)))
            synthesize(request['text'], request['output'])
            signal.alarm(0)
            print('{"ok":true}', file=reply_stream, flush=True)


if __name__ == '__main__':
    main()

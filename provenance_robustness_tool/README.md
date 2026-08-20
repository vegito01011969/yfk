# Video Robustness Transform Tool

Local CLI for generating one randomized, perceptually similar derivative of a video for provenance and traceability robustness testing.

This tool is intended for authorized evaluation of provenance systems. It does not target or optimize against any specific detector, watermark, or traceability system.

## Requirements

- Python 3.10+
- FFmpeg and FFprobe available on `PATH`

No Python packages are required.

## Usage

```bash
python transform.py input.mp4
```

The command writes:

- `input_robustness_<seed>.mp4`
- `input_robustness_<seed>.mp4.debug.json`

Optional reproducible run:

```bash
python transform.py input.mp4 --seed 12345
```

Optional explicit output:

```bash
python transform.py input.mp4 --output output.mp4
```

Optional benchmark hardness:

```bash
python transform.py input.mp4 --level 6
```

Levels are detector-agnostic stress profiles:

- `0`: validation-rescue style light transform
- `1`: light single/few-operation transform
- `2`: moderate paired transforms
- `3`: several composed transforms
- `4`: default composed benchmark
- `5`: heavy composed benchmark with occasional overlays and codec generations
- `6`: strongest local stress profile, still validated for similarity and playability

## Self-Test Report

After generating a derivative, compare the original and output:

```bash
python compare.py input.mp4 output.mp4 --output comparison_report.json
```

The report includes:

- whole-file SHA-256 hashes
- decoded video/audio stream hashes
- codec, timing, bitrate, and stream metadata
- duration drift
- sampled SSIM and PSNR perceptual metrics

For a good robustness-test derivative, expect:

- file hashes differ
- decoded stream hashes differ
- codecs/timing/bitrate/container details differ
- duration drift remains very small
- SSIM remains high enough for obvious perceptual similarity

This report does not predict whether a specific provenance system will match the source. It only verifies that the sample is both perceptually close and technically transformed enough to be a meaningful black-box test case.

## What It Does

The tool automatically inspects the input and builds a randomized transform plan from one of several perceptual stress profiles:

- small crop and resize back to the original dimensions
- slight working-resolution overscan followed by micro-rotation and center crop
- randomized scaler kernels, sub-pixel translation, and a second resize pass
- mild non-uniform scaling, keystone/perspective perturbation, and affine-style reframing
- slight brightness, contrast, saturation, and gamma adjustment
- tiny hue adjustment
- subtle RGB channel mixing, color-temperature shift, chroma-plane shifts, and debanding
- optional spatially varying brightness/tint, vignette, posterization, blur, and edge matte
- mild denoise, temporal grain mixing, synthetic noise, blur, and sharpening changes
- small frame-rate and timing normalization
- short fade/flash/progress-bar/watermark-style overlays on higher stress levels
- audio high/low-pass normalization, bass/treble shaping, randomized parametric and dynamic EQ, FFT denoise, phase shifting, spectral tilt, stereo expansion, Haas/crossfeed spatial changes, crystalizer sharpening, dynamic compression, companding, dynamic normalization, speech normalization, limiting, high-quality multi-stage resampling with randomized dithering, small volume adjustment, pitch/time changes through resampling and optional Rubber Band processing, stereo field remixing, low-rate tremolo, synchronized tempo matching, optional phaser/flanger/micro echo, optional small A/V delay, and layered low-volume generated noise/hum/tone/texture beds
- higher stress levels can run audio through MP3/Opus/AAC codec generations before the final transform, then apply a synthetic room impulse response through convolution reverb so the decoded waveform is changed more substantially while preserving recognizable content
- metadata/chapter stripping
- H.264/AAC encoding with randomized sane encoder settings, GOP structure, reference frames, B-frames, adaptive quantization, profile/level, tune, deblock, trellis, lookahead, and psycho-visual parameters
- optional multi-generation codec pass before the final transform, such as H.264/H.265 round trips
- MP4 output with fast-start layout, varied video track timescale, randomized muxer flags, and optional reserved metadata padding

It validates the output for:

- playability via `ffprobe`
- duration drift
- expected audio presence
- valid video dimensions
- sampled SSIM perceptual similarity with enough tolerance for visibly transformed-but-similar outputs
- changed file hash
- minimum technical-difference score across timing, size, frame-rate, codec, and container characteristics

If validation fails, it retries with a new transform plan. Early attempts now bias toward stronger perceptual-shift and representation-heavy profiles. Later attempts bias toward safer perceptual-close settings, and the final attempt uses a conservative validation-rescue profile that preserves geometry while still re-encoding, retiming, remuxing, and lightly adjusting audio/video. Intermediate files are cleaned automatically.

The debug JSON records the selected stress level, selected operations, stress profile, every randomized parameter, every validation attempt, sampled SSIM, duration drift, file-size delta, frame-rate delta, and the technical-difference score. Keep that file with test results if you need reproducibility.

## Suggested Blind Evaluation

Use a held-out set of originals your colleague has not tuned against. Generate derivatives with fixed seeds and keep the debug records private until after scoring. Evaluate whether the provenance system ranks the true source highly among a candidate corpus, not just whether it says "match" for a known pair.

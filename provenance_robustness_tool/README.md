# Video Robustness Transform Tool

Local CLI for generating one randomized, perceptually close derivative of a video for provenance and traceability robustness testing.

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
- slight brightness, contrast, saturation, and gamma adjustment
- tiny hue adjustment
- subtle RGB channel mixing, chroma-plane shifts, and debanding
- mild denoise, temporal grain mixing, synthetic noise, and sharpening changes
- small frame-rate and timing normalization
- audio high/low-pass normalization, subtle compression, slight EQ, high-quality resampling with randomized dithering, small volume adjustment, and synchronized tempo matching
- metadata/chapter stripping
- H.264/AAC encoding with randomized sane encoder settings, GOP structure, reference frames, B-frames, adaptive quantization, profile/level, tune, deblock, trellis, lookahead, and psycho-visual parameters
- MP4 output with fast-start layout, varied video track timescale, randomized muxer flags, and optional reserved metadata padding

It validates the output for:

- playability via `ffprobe`
- duration drift
- expected audio presence
- valid video dimensions
- sampled SSIM perceptual similarity
- changed file hash
- minimum technical-difference score across timing, size, frame-rate, codec, and container characteristics

If validation fails, it retries with a new transform plan. Later attempts bias toward safer perceptual-close settings, and the final attempt uses a conservative validation-rescue profile that preserves geometry while still re-encoding, retiming, remuxing, and lightly adjusting audio/video. Intermediate files are cleaned automatically.

The debug JSON records the selected stress profile, every randomized parameter, every validation attempt, sampled SSIM, duration drift, file-size delta, frame-rate delta, and the technical-difference score. Keep that file with test results if you need reproducibility.

## Suggested Blind Evaluation

Use a held-out set of originals your colleague has not tuned against. Generate derivatives with fixed seeds and keep the debug records private until after scoring. Evaluate whether the provenance system ranks the true source highly among a candidate corpus, not just whether it says "match" for a known pair.

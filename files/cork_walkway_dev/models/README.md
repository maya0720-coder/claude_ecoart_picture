# models/ — 길 자동 지정(SAM 계열) ONNX 모델

이 폴더에 아래 두 파일을 넣으면 터치로 길을 자동 지정할 수 있다. 파일이 없으면 브러시·지우개·다각형 수동 도구만으로 동작한다.
파일명은 `config.yaml`의 `segmentation.encoder` / `segmentation.decoder`와 같아야 한다.

| 파일 | 크기 | SHA-256 |
|---|---|---|
| `mobile_sam_image_encoder.onnx` | 28,157,093 B | `580f5fb648ea1062c0aabc26217aed56921985f03f0cbbd852bba81d760cc749` |
| `sam_mask_decoder_multi.onnx` | 16,496,559 B | `8976b90a87ba50a6a72217a5ff994f7d25ce16f2229fcc1ed259e1294c622ffe` |

- 받은 곳: Hugging Face `Heliosoph/sam-onnx` (커밋 `465be8e75889fea5afd37924f678ad6559ed5439`)
  `https://huggingface.co/Heliosoph/sam-onnx/resolve/465be8e75889fea5afd37924f678ad6559ed5439/<파일명>`
- 원 모델: MobileSAM ViT-T 인코더(Chaoning Zhang 외, https://github.com/ChaoningZhang/MobileSAM) + Meta Segment Anything 마스크 디코더(https://github.com/facebookresearch/segment-anything)
- 라이선스: Apache-2.0 (`LICENSE_mobile_sam.md`). 원 프로젝트 두 곳 모두 Apache-2.0
- **확인 필요:** 위 배포본은 개인이 올린 재배포본이라 변환 과정을 검증할 수 없다. 상용 배포 전에는 MobileSAM 공식 체크포인트(`mobile_sam.pt`)에서 직접 ONNX로 변환한 파일로 바꾸는 것을 권장한다.
  같은 입출력 형식이면 코드 수정 없이 교체할 수 있다.
  - 인코더: 입력 `input_image` (H, W, 3) float32 RGB 0~255, 긴 변 1024
  - 디코더: SAM 공식 ONNX 디코더 형식
- 앱은 모델을 인터넷에서 자동으로 받지 않는다(모듈 10 규칙). 사용자가 직접 넣는다.

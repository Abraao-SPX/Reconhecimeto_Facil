#!/bin/bash
set -e

echo "Downloading YuNet model..."
wget -q -O face_detection_yunet_2023mar.onnx "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"

echo "Downloading SFace model..."
wget -q -O face_recognition_sface_2021dec.onnx "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

echo "Downloading MiniFASNet Anti-Spoofing model..."
wget -q -O MiniFASNetV2.onnx "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx"

echo "Models downloaded successfully."

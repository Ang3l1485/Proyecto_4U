import 'dart:typed_data';

import '../entities/image_quality_report.dart';

abstract interface class CaptureQualityAnalyzer {
  ImageQualityReport analyzeImage(Uint8List imageBytes);
}

class ImageQualityThresholds {
  const ImageQualityThresholds({
    required this.minimumWidth,
    required this.minimumHeight,
    required this.minimumBrightness,
    required this.minimumSharpness,
  });

  final int minimumWidth;
  final int minimumHeight;
  final double minimumBrightness;
  final double minimumSharpness;
}

class ValidateCapture {
  const ValidateCapture(this._analyzer);

  final CaptureQualityAnalyzer _analyzer;

  ImageQualityReport validateCapture(Uint8List imageBytes) {
    return _analyzer.analyzeImage(imageBytes);
  }
}

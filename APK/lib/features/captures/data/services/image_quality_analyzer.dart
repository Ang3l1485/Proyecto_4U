import 'dart:math' as math;
import 'dart:typed_data';

import 'package:image/image.dart' as image;

import '../../domain/entities/image_quality_report.dart';
import '../../domain/use_cases/validate_capture.dart';

class ImageQualityAnalyzer implements CaptureQualityAnalyzer {
  const ImageQualityAnalyzer(this._thresholds);

  final ImageQualityThresholds _thresholds;

  @override
  ImageQualityReport analyzeImage(Uint8List imageBytes) {
    final image.Image? decodedImage;
    try {
      decodedImage = image.decodeImage(imageBytes);
    } catch (_) {
      return _unreadableReport();
    }
    if (decodedImage == null) {
      return _unreadableReport();
    }

    final double brightness = _averageBrightness(decodedImage);
    final double sharpness = _sharpnessScore(decodedImage);
    final List<String> rejectionReasons = <String>[];
    if (decodedImage.width < _thresholds.minimumWidth ||
        decodedImage.height < _thresholds.minimumHeight) {
      rejectionReasons.add(
        'La resolución es ${decodedImage.width}x${decodedImage.height}; '
        'el mínimo es ${_thresholds.minimumWidth}x${_thresholds.minimumHeight}.',
      );
    }
    if (brightness < _thresholds.minimumBrightness) {
      rejectionReasons.add(
        'La iluminación es insuficiente (${brightness.toStringAsFixed(1)}); '
        'el mínimo es ${_thresholds.minimumBrightness.toStringAsFixed(1)}.',
      );
    }
    if (sharpness < _thresholds.minimumSharpness) {
      rejectionReasons.add(
        'La nitidez es insuficiente (${sharpness.toStringAsFixed(1)}); '
        'el mínimo es ${_thresholds.minimumSharpness.toStringAsFixed(1)}.',
      );
    }

    return ImageQualityReport(
      width: decodedImage.width,
      height: decodedImage.height,
      averageBrightness: brightness,
      sharpnessScore: sharpness,
      rejectionReasons: rejectionReasons,
    );
  }

  ImageQualityReport _unreadableReport() {
    return const ImageQualityReport(
      width: 0,
      height: 0,
      averageBrightness: 0,
      sharpnessScore: 0,
      rejectionReasons: <String>[
        'La imagen no se pudo leer en un formato compatible.',
      ],
    );
  }

  double _averageBrightness(image.Image source) {
    final int step = _sampleStep(source);
    double total = 0;
    int sampleCount = 0;
    for (int y = 0; y < source.height; y += step) {
      for (int x = 0; x < source.width; x += step) {
        total += _luminance(source.getPixel(x, y));
        sampleCount++;
      }
    }
    return sampleCount == 0 ? 0 : total / sampleCount;
  }

  double _sharpnessScore(image.Image source) {
    final int step = _sampleStep(source);
    double totalDifference = 0;
    int comparisonCount = 0;
    for (int y = 0; y < source.height; y += step) {
      for (int x = 0; x < source.width - step; x += step) {
        final double current = _luminance(source.getPixel(x, y));
        final double next = _luminance(source.getPixel(x + step, y));
        totalDifference += (current - next).abs();
        comparisonCount++;
      }
    }
    return comparisonCount == 0 ? 0 : totalDifference / comparisonCount;
  }

  int _sampleStep(image.Image source) {
    return math.max(1, math.sqrt(source.width * source.height / 5000).round());
  }

  double _luminance(image.Pixel pixel) {
    return (0.2126 * pixel.r.toDouble()) +
        (0.7152 * pixel.g.toDouble()) +
        (0.0722 * pixel.b.toDouble());
  }
}

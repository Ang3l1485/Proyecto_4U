import 'dart:typed_data';

import 'package:dataset_app/features/captures/data/services/image_quality_analyzer.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/domain/use_cases/validate_capture.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as image;

void main() {
  const ImageQualityAnalyzer analyzer = ImageQualityAnalyzer(
    ImageQualityThresholds(
      minimumWidth: 8,
      minimumHeight: 8,
      minimumBrightness: 30,
      minimumSharpness: 5,
    ),
  );

  test('rejects unreadable image bytes', () {
    final ImageQualityReport report = analyzer.analyzeImage(
      Uint8List.fromList(<int>[1, 2, 3]),
    );

    expect(report.isAccepted, isFalse);
    expect(report.width, 0);
    expect(report.rejectionReasons.single, contains('formato compatible'));
  });

  test('reports resolution, darkness and lack of sharpness', () {
    final image.Image source = image.Image(width: 4, height: 4);
    image.fill(source, color: image.ColorRgb8(0, 0, 0));

    final ImageQualityReport report = analyzer.analyzeImage(
      Uint8List.fromList(image.encodePng(source)),
    );

    expect(report.isAccepted, isFalse);
    expect(report.rejectionReasons, hasLength(3));
  });

  test('accepts a bright image with visible edges', () {
    final image.Image source = image.Image(width: 8, height: 8);
    for (int y = 0; y < source.height; y++) {
      for (int x = 0; x < source.width; x++) {
        final int value = x.isEven ? 255 : 40;
        source.setPixelRgb(x, y, value, value, value);
      }
    }

    final ImageQualityReport report = analyzer.analyzeImage(
      Uint8List.fromList(image.encodePng(source)),
    );

    expect(report.isAccepted, isTrue);
  });
}

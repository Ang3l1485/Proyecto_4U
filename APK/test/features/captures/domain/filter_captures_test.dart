import 'package:dataset_app/features/captures/domain/entities/capture.dart';
import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/domain/use_cases/filter_captures.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const FilterCaptures filterCaptures = FilterCaptures();

  test('filters block without case sensitivity', () {
    final List<Capture> result = filterCaptures.filterCaptures(<Capture>[
      _capture('1', 'Bloque Norte', DateTime(2026, 8, 23)),
      _capture('2', 'Sur', DateTime(2026, 8, 23)),
    ], const CaptureFilter(blockQuery: 'NORTE'));

    expect(result.map((Capture capture) => capture.id), <String>['1']);
  });

  test('includes every instant of the selected end date', () {
    final List<Capture> result = filterCaptures.filterCaptures(
      <Capture>[
        _capture('start', 'A', DateTime(2026, 8, 22)),
        _capture('late', 'A', DateTime(2026, 8, 23, 23, 59, 59, 999)),
        _capture('next', 'A', DateTime(2026, 8, 24)),
      ],
      CaptureFilter(
        fromDate: DateTime(2026, 8, 22),
        toDate: DateTime(2026, 8, 23),
      ),
    );

    expect(result.map((Capture capture) => capture.id), <String>[
      'start',
      'late',
    ]);
  });
}

Capture _capture(String id, String block, DateTime timestamp) {
  return Capture(
    id: id,
    imagePath: '$id.jpg',
    metadataPath: '$id.json',
    metadata: CaptureMetadata(
      block: block,
      latitude: 0,
      longitude: 0,
      timestamp: timestamp,
      author: 'Test',
      sessionId: 'session',
      status: MetadataStatus.complete,
    ),
    quality: const ImageQualityReport(
      width: 1,
      height: 1,
      averageBrightness: 1,
      sharpnessScore: 1,
      rejectionReasons: <String>[],
    ),
    wasQualityOverride: false,
  );
}

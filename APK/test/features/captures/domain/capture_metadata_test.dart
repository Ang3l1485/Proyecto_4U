import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('maps campus zones to persisted values and labels', () {
    expect(CampusZone.bloque32.persistedValue, 'Biblioteca');
    expect(CampusZone.bloque32.label, 'Biblioteca');
    expect(CampusZone.bloque38.persistedValue, 'bloque38');
    expect(CampusZone.bloque38.label, 'Bloque 38');
  });

  test('resolves current and legacy campus zone values', () {
    expect(CampusZone.fromBlock('Biblioteca'), CampusZone.bloque32);
    expect(CampusZone.fromBlock('bloque32'), CampusZone.bloque32);
    expect(CampusZone.fromBlock('bloque38'), CampusZone.bloque38);
  });

  test('serializes and deserializes all active metadata fields', () {
    final CaptureMetadata original = CaptureMetadata(
      block: 'B-12',
      latitude: 4.6351,
      longitude: -74.0823,
      timestamp: DateTime.parse('2026-08-23T14:30:00-05:00'),
      author: 'Ana',
      sessionId: 'session-1',
      status: MetadataStatus.complete,
      compassHeadingDegrees: 91.5,
      compassDirection: 'E',
    );

    final Map<String, Object?> json = original.toJson();
    final CaptureMetadata restored = CaptureMetadata.fromJson(json);

    expect(restored.block, original.block);
    expect(restored.latitude, original.latitude);
    expect(restored.longitude, original.longitude);
    expect(restored.timestamp, original.timestamp);
    expect(restored.author, original.author);
    expect(restored.sessionId, original.sessionId);
    expect(restored.status, MetadataStatus.complete);
    expect(restored.floor, isNull);
    expect(restored.compassHeadingDegrees, 91.5);
    expect(restored.compassDirection, 'E');
    expect(json, isNot(contains('zone')));
    expect(json, isNot(contains('place')));
    expect(json, containsPair('floor', isNull));
  });

  test('reads legacy JSON while ignoring retired location fields', () {
    final CaptureMetadata metadata = CaptureMetadata.fromJson(<String, Object?>{
      'zone': <String, String>{'id': 'old', 'name': 'Old'},
      'place': <String, String>{'id': 'old', 'name': 'Old'},
      'floor': '3',
      'block': 'A',
      'coordinates': <String, double>{'latitude': 1, 'longitude': 2},
      'timestamp': '2026-08-23T10:00:00',
      'author': 'Luis',
      'sessionId': 'legacy',
      'status': 'pending',
      'compassHeadingDegrees': 225,
    });

    expect(metadata.block, 'A');
    expect(metadata.compassDirection, 'SW');
  });
}

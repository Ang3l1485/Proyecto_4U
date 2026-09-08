enum MetadataStatus {
  pending,
  complete;

  static MetadataStatus fromName(String? name) {
    return MetadataStatus.values.firstWhere(
      (MetadataStatus status) => status.name == name,
      orElse: () => MetadataStatus.pending,
    );
  }
}

enum CampusZone {
  bloque32,
  bloque38;

  String get persistedValue {
    switch (this) {
      case CampusZone.bloque32:
        return 'Biblioteca';
      case CampusZone.bloque38:
        return 'bloque38';
    }
  }

  String get label {
    switch (this) {
      case CampusZone.bloque32:
        return 'Biblioteca';
      case CampusZone.bloque38:
        return 'Bloque 38';
    }
  }

  static CampusZone? fromBlock(String block) {
    for (final CampusZone zone in values) {
      if (zone.persistedValue == block ||
          (zone == CampusZone.bloque32 && block == zone.name)) {
        return zone;
      }
    }
    return null;
  }
}

class CaptureMetadata {
  const CaptureMetadata({
    required this.block,
    required this.latitude,
    required this.longitude,
    required this.timestamp,
    required this.author,
    required this.sessionId,
    required this.status,
    this.floor,
    this.compassHeadingDegrees,
    this.compassDirection,
  });

  final String block;
  final double latitude;
  final double longitude;
  final DateTime timestamp;
  final String author;
  final String sessionId;
  final MetadataStatus status;
  final int? floor;
  final double? compassHeadingDegrees;
  final String? compassDirection;

  bool get isReadyForTraining => status == MetadataStatus.complete;

  String get imageLabel {
    final String headingLabel = compassHeadingDegrees == null
        ? 'no disponible'
        : '${compassDirection ?? directionFromHeading(compassHeadingDegrees!)} '
              '(${compassHeadingDegrees!.toStringAsFixed(1)}°)';
    return '$block | lat: ${latitude.toStringAsFixed(6)} | '
        'lon: ${longitude.toStringAsFixed(6)} | rumbo: $headingLabel | '
        'recolector: $author';
  }

  CaptureMetadata copyWith({
    String? block,
    double? latitude,
    double? longitude,
    DateTime? timestamp,
    String? author,
    String? sessionId,
    MetadataStatus? status,
    int? floor,
    double? compassHeadingDegrees,
    String? compassDirection,
  }) {
    return CaptureMetadata(
      block: block ?? this.block,
      latitude: latitude ?? this.latitude,
      longitude: longitude ?? this.longitude,
      timestamp: timestamp ?? this.timestamp,
      author: author ?? this.author,
      sessionId: sessionId ?? this.sessionId,
      status: status ?? this.status,
      floor: floor ?? this.floor,
      compassHeadingDegrees:
          compassHeadingDegrees ?? this.compassHeadingDegrees,
      compassDirection: compassDirection ?? this.compassDirection,
    );
  }

  Map<String, Object?> toJson() {
    return <String, Object?>{
      'block': block,
      'coordinates': <String, double>{
        'latitude': latitude,
        'longitude': longitude,
      },
      'timestamp': timestamp.toIso8601String(),
      'author': author,
      'sessionId': sessionId,
      'status': status.name,
      'floor': floor,
      'compassHeadingDegrees': compassHeadingDegrees,
      'compassDirection': compassDirection,
    };
  }

  factory CaptureMetadata.fromJson(Map<String, Object?> json) {
    final Object? rawCoordinates = json['coordinates'];
    final Map<String, Object?> coordinates =
        rawCoordinates is Map<Object?, Object?>
        ? rawCoordinates.cast<String, Object?>()
        : <String, Object?>{};
    final double? heading = (json['compassHeadingDegrees'] as num?)?.toDouble();
    final String? storedDirection = json['compassDirection'] as String?;
    final Object? rawFloor = json['floor'];
    final int? floor = rawFloor is num ? rawFloor.toInt() : null;

    return CaptureMetadata(
      block: json['block'] as String? ?? '',
      latitude: (coordinates['latitude'] as num?)?.toDouble() ?? 0,
      longitude: (coordinates['longitude'] as num?)?.toDouble() ?? 0,
      timestamp:
          DateTime.tryParse(json['timestamp'] as String? ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
      author: json['author'] as String? ?? '',
      sessionId: json['sessionId'] as String? ?? '',
      status: MetadataStatus.fromName(json['status'] as String?),
      floor: floor,
      compassHeadingDegrees: heading,
      compassDirection:
          storedDirection ??
          (heading == null ? null : directionFromHeading(heading)),
    );
  }

  static String directionFromHeading(double headingDegrees) {
    const List<String> directions = <String>[
      'N',
      'NE',
      'E',
      'SE',
      'S',
      'SW',
      'W',
      'NW',
    ];
    final double normalized = ((headingDegrees % 360) + 360) % 360;
    final int index = ((normalized + 22.5) / 45).floor() % directions.length;
    return directions[index];
  }
}

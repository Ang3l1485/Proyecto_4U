import 'capture_metadata.dart';
import 'image_quality_report.dart';

class Capture {
  const Capture({
    required this.id,
    required this.imagePath,
    required this.metadataPath,
    required this.metadata,
    required this.quality,
    required this.wasQualityOverride,
  });

  final String id;
  final String imagePath;
  final String metadataPath;
  final CaptureMetadata metadata;
  final ImageQualityReport quality;
  final bool wasQualityOverride;

  Capture copyWith({CaptureMetadata? metadata}) {
    return Capture(
      id: id,
      imagePath: imagePath,
      metadataPath: metadataPath,
      metadata: metadata ?? this.metadata,
      quality: quality,
      wasQualityOverride: wasQualityOverride,
    );
  }

  Map<String, Object?> toJson() {
    return <String, Object?>{
      'id': id,
      'imagePath': imagePath,
      'metadataPath': metadataPath,
      'metadata': metadata.toJson(),
      'quality': quality.toJson(),
      'wasQualityOverride': wasQualityOverride,
    };
  }

  factory Capture.fromJson(Map<String, Object?> json) {
    final Object? rawMetadata = json['metadata'];
    final Object? rawQuality = json['quality'];
    if (rawMetadata is! Map<Object?, Object?> ||
        rawQuality is! Map<Object?, Object?>) {
      throw const FormatException('Registro de captura incompleto.');
    }
    return Capture(
      id: json['id'] as String? ?? '',
      imagePath: json['imagePath'] as String? ?? '',
      metadataPath: json['metadataPath'] as String? ?? '',
      metadata: CaptureMetadata.fromJson(rawMetadata.cast<String, Object?>()),
      quality: ImageQualityReport.fromJson(rawQuality.cast<String, Object?>()),
      wasQualityOverride: json['wasQualityOverride'] as bool? ?? false,
    );
  }
}

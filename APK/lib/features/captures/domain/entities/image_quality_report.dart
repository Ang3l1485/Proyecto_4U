class ImageQualityReport {
  const ImageQualityReport({
    required this.width,
    required this.height,
    required this.averageBrightness,
    required this.sharpnessScore,
    required this.rejectionReasons,
  });

  final int width;
  final int height;
  final double averageBrightness;
  final double sharpnessScore;
  final List<String> rejectionReasons;

  bool get isAccepted => rejectionReasons.isEmpty;
  double get selectionScore => sharpnessScore + (averageBrightness / 10);

  Map<String, Object?> toJson() {
    return <String, Object?>{
      'width': width,
      'height': height,
      'averageBrightness': averageBrightness,
      'sharpnessScore': sharpnessScore,
      'rejectionReasons': rejectionReasons,
    };
  }

  factory ImageQualityReport.fromJson(Map<String, Object?> json) {
    final Object? rawReasons = json['rejectionReasons'];
    return ImageQualityReport(
      width: (json['width'] as num?)?.toInt() ?? 0,
      height: (json['height'] as num?)?.toInt() ?? 0,
      averageBrightness: (json['averageBrightness'] as num?)?.toDouble() ?? 0,
      sharpnessScore: (json['sharpnessScore'] as num?)?.toDouble() ?? 0,
      rejectionReasons: rawReasons is List<Object?>
          ? rawReasons.map((Object? reason) => reason.toString()).toList()
          : <String>[],
    );
  }
}

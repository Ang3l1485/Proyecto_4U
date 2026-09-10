class CompassReading {
  const CompassReading(this.headingDegrees);

  final double headingDegrees;
}

abstract interface class CompassService {
  bool get isAvailable;
  String get availabilityMessage;
  Stream<CompassReading> get readings;
}

import 'package:flutter/foundation.dart';
import 'package:flutter_compass/flutter_compass.dart';

import 'compass_service.dart';

class FlutterCompassService implements CompassService {
  @override
  bool get isAvailable {
    return !kIsWeb &&
        (defaultTargetPlatform == TargetPlatform.android ||
            defaultTargetPlatform == TargetPlatform.iOS);
  }

  @override
  String get availabilityMessage {
    if (defaultTargetPlatform == TargetPlatform.windows) {
      return 'La brújula no está disponible en Windows.';
    }
    return isAvailable
        ? 'Brújula disponible.'
        : 'La brújula no está disponible en esta plataforma.';
  }

  @override
  Stream<CompassReading> get readings {
    if (!isAvailable) {
      return const Stream<CompassReading>.empty();
    }
    final Stream<CompassEvent>? events = FlutterCompass.events;
    if (events == null) {
      return const Stream<CompassReading>.empty();
    }
    return events
        .where((CompassEvent event) => event.heading?.isFinite ?? false)
        .map((CompassEvent event) => CompassReading(event.heading!));
  }
}

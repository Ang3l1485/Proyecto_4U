import 'package:geolocator/geolocator.dart';

import 'location_service.dart';

class GeolocatorLocationService implements LocationService {
  const GeolocatorLocationService();

  @override
  Future<CurrentLocation> getCurrentLocation() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw StateError(
        'El servicio de ubicación está desactivado. Actívalo e intenta de nuevo.',
      );
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) {
      throw StateError(
        'El permiso de ubicación está bloqueado. Actívalo en la configuración del sistema.',
      );
    }
    if (permission == LocationPermission.denied) {
      throw StateError('Se requiere permiso de ubicación para obtener el GPS.');
    }

    final Position position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.medium,
      ),
    );
    return CurrentLocation(
      latitude: position.latitude,
      longitude: position.longitude,
    );
  }
}

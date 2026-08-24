class CurrentLocation {
  const CurrentLocation({required this.latitude, required this.longitude});

  final double latitude;
  final double longitude;
}

abstract interface class LocationService {
  Future<CurrentLocation> getCurrentLocation();
}

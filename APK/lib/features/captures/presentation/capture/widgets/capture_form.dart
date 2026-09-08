import 'package:flutter/material.dart';

import '../../../domain/entities/capture_metadata.dart';

class CaptureFormData {
  const CaptureFormData({
    required this.block,
    required this.latitude,
    required this.longitude,
    required this.author,
    required this.status,
  });

  final String block;
  final double latitude;
  final double longitude;
  final String author;
  final MetadataStatus status;
}

class CaptureForm extends StatefulWidget {
  const CaptureForm({
    required super.key,
    required this.sessionId,
    required this.isGettingLocation,
    required this.onRequestLocation,
  });

  final String sessionId;
  final bool isGettingLocation;
  final VoidCallback onRequestLocation;

  @override
  State<CaptureForm> createState() => CaptureFormState();
}

class CaptureFormState extends State<CaptureForm> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _latitudeController = TextEditingController();
  final TextEditingController _longitudeController = TextEditingController();
  final TextEditingController _authorController = TextEditingController();
  CampusZone? _zone;
  MetadataStatus _status = MetadataStatus.pending;

  CaptureFormData? validateAndRead() {
    if (!(_formKey.currentState?.validate() ?? false)) {
      return null;
    }
    return CaptureFormData(
      block: _zone!.persistedValue,
      latitude: double.parse(_latitudeController.text.trim()),
      longitude: double.parse(_longitudeController.text.trim()),
      author: _authorController.text.trim(),
      status: _status,
    );
  }

  void setCoordinates({required double latitude, required double longitude}) {
    _latitudeController.text = latitude.toStringAsFixed(6);
    _longitudeController.text = longitude.toStringAsFixed(6);
  }

  void clearAfterSave() {
    _zone = null;
    _latitudeController.clear();
    _longitudeController.clear();
    _authorController.clear();
    setState(() => _status = MetadataStatus.pending);
  }

  @override
  void dispose() {
    _latitudeController.dispose();
    _longitudeController.dispose();
    _authorController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        children: <Widget>[
          DropdownButtonFormField<CampusZone>(
            initialValue: _zone,
            decoration: const InputDecoration(
              labelText: 'Lugar',
              border: OutlineInputBorder(),
            ),
            items: CampusZone.values
                .map(
                  (CampusZone zone) => DropdownMenuItem<CampusZone>(
                    value: zone,
                    child: Text(zone.label),
                  ),
                )
                .toList(growable: false),
            validator: (CampusZone? value) =>
                value == null ? 'El lugar es obligatorio.' : null,
            onChanged: (CampusZone? value) {
              setState(() => _zone = value);
            },
          ),
          const SizedBox(height: 12),
          Row(
            children: <Widget>[
              Expanded(
                child: TextFormField(
                  controller: _latitudeController,
                  decoration: const InputDecoration(
                    labelText: 'Latitud',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                    signed: true,
                  ),
                  validator: (String? value) =>
                      _coordinate(value, 'La latitud', -90, 90),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextFormField(
                  controller: _longitudeController,
                  decoration: const InputDecoration(
                    labelText: 'Longitud',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                    signed: true,
                  ),
                  validator: (String? value) =>
                      _coordinate(value, 'La longitud', -180, 180),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: widget.isGettingLocation
                  ? null
                  : widget.onRequestLocation,
              icon: widget.isGettingLocation
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.my_location),
              label: Text(
                widget.isGettingLocation
                    ? 'Obteniendo ubicación…'
                    : 'Usar ubicación actual',
              ),
            ),
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _authorController,
            decoration: const InputDecoration(
              labelText: 'Nombre del recolector',
              border: OutlineInputBorder(),
            ),
            validator: (String? value) => _required(value, 'El recolector'),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<MetadataStatus>(
            initialValue: _status,
            decoration: const InputDecoration(
              labelText: 'Estado de metadatos',
              border: OutlineInputBorder(),
            ),
            items: const <DropdownMenuItem<MetadataStatus>>[
              DropdownMenuItem<MetadataStatus>(
                value: MetadataStatus.pending,
                child: Text('Pendiente'),
              ),
              DropdownMenuItem<MetadataStatus>(
                value: MetadataStatus.complete,
                child: Text('Completo / listo para entrenamiento'),
              ),
            ],
            onChanged: (MetadataStatus? value) {
              setState(() => _status = value ?? MetadataStatus.pending);
            },
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: Text('Sesión: ${widget.sessionId}'),
          ),
        ],
      ),
    );
  }

  String? _required(String? value, String label) {
    return value == null || value.trim().isEmpty
        ? '$label es obligatorio.'
        : null;
  }

  String? _coordinate(
    String? value,
    String label,
    double minimum,
    double maximum,
  ) {
    final String? requiredMessage = _required(value, label);
    if (requiredMessage != null) {
      return requiredMessage;
    }
    final double? coordinate = double.tryParse(value!.trim());
    if (coordinate == null) {
      return '$label debe ser numérica.';
    }
    if (coordinate < minimum || coordinate > maximum) {
      return '$label debe estar entre $minimum y $maximum.';
    }
    return null;
  }
}

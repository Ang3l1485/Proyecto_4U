import 'package:flutter/material.dart';

import '../../../domain/entities/capture.dart';
import '../../../domain/entities/capture_metadata.dart';
import '../../../domain/use_cases/update_capture_metadata.dart';

class CaptureEditor extends StatefulWidget {
  const CaptureEditor({
    super.key,
    required this.capture,
    required this.isSaving,
    required this.onSave,
    required this.onCancel,
  });

  final Capture capture;
  final bool isSaving;
  final ValueChanged<CaptureMetadataChanges> onSave;
  final VoidCallback onCancel;

  @override
  State<CaptureEditor> createState() => _CaptureEditorState();
}

class _CaptureEditorState extends State<CaptureEditor> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  late final TextEditingController _latitudeController;
  late final TextEditingController _longitudeController;
  late final TextEditingController _authorController;
  CampusZone? _zone;
  late final TextEditingController _floorController;
  late MetadataStatus _status;

  @override
  void initState() {
    super.initState();
    final CaptureMetadata metadata = widget.capture.metadata;
    _zone = CampusZone.fromBlock(metadata.block);
    _latitudeController = TextEditingController(
      text: metadata.latitude.toString(),
    );
    _longitudeController = TextEditingController(
      text: metadata.longitude.toString(),
    );
    _authorController = TextEditingController(text: metadata.author);
    _floorController = TextEditingController(
      text: metadata.floor?.toString() ?? '',
    );
    _status = metadata.status;
  }

  @override
  void dispose() {
    _latitudeController.dispose();
    _longitudeController.dispose();
    _authorController.dispose();
    _floorController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Form(
          key: _formKey,
          child: Column(
            children: <Widget>[
              Text(
                'Editar captura',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<CampusZone>(
                initialValue: _zone,
                decoration: const InputDecoration(labelText: 'Lugar'),
                items: CampusZone.values
                    .map(
                      (CampusZone zone) => DropdownMenuItem<CampusZone>(
                        value: zone,
                        child: Text(zone.label),
                      ),
                    )
                    .toList(growable: false),
                validator: (CampusZone? value) =>
                    value == null ? 'Campo obligatorio.' : null,
                onChanged: (CampusZone? value) {
                  setState(() => _zone = value);
                },
              ),
              TextFormField(
                controller: _latitudeController,
                decoration: const InputDecoration(labelText: 'Latitud'),
                validator: (String? value) => _coordinate(value, -90, 90),
              ),
              TextFormField(
                controller: _longitudeController,
                decoration: const InputDecoration(labelText: 'Longitud'),
                validator: (String? value) => _coordinate(value, -180, 180),
              ),
              TextFormField(
                controller: _authorController,
                decoration: const InputDecoration(labelText: 'Recolector'),
                validator: _required,
              ),
              TextFormField(
                controller: _floorController,
                decoration: const InputDecoration(labelText: 'Piso'),
                keyboardType: TextInputType.number,
                validator: (String? value) => _integer(value, 'El piso'),
              ),
              const SizedBox(height: 8),
              DropdownButtonFormField<MetadataStatus>(
                initialValue: _status,
                decoration: const InputDecoration(labelText: 'Estado'),
                items: const <DropdownMenuItem<MetadataStatus>>[
                  DropdownMenuItem<MetadataStatus>(
                    value: MetadataStatus.pending,
                    child: Text('Pendiente'),
                  ),
                  DropdownMenuItem<MetadataStatus>(
                    value: MetadataStatus.complete,
                    child: Text('Completo'),
                  ),
                ],
                onChanged: (MetadataStatus? value) {
                  setState(() => _status = value ?? MetadataStatus.pending);
                },
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                children: <Widget>[
                  FilledButton(
                    onPressed: widget.isSaving ? null : _submit,
                    child: const Text('Guardar cambios'),
                  ),
                  TextButton(
                    onPressed: widget.isSaving ? null : widget.onCancel,
                    child: const Text('Cancelar'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) {
      return;
    }
    widget.onSave(
      CaptureMetadataChanges(
        block: _zone!.persistedValue,
        latitude: double.parse(_latitudeController.text),
        longitude: double.parse(_longitudeController.text),
        author: _authorController.text,
        status: _status,
        floor: int.tryParse(_floorController.text.trim()),
      ),
    );
  }

  String? _required(String? value) {
    return value == null || value.trim().isEmpty ? 'Campo obligatorio.' : null;
  }

  String? _coordinate(String? value, double minimum, double maximum) {
    final double? coordinate = double.tryParse(value?.trim() ?? '');
    if (coordinate == null) {
      return 'Ingresa un número válido.';
    }
    return coordinate < minimum || coordinate > maximum
        ? 'Debe estar entre $minimum y $maximum.'
        : null;
  }

  String? _integer(String? value, String label) {
    if (value == null || value.trim().isEmpty) {
      return null;
    }
    return int.tryParse(value.trim()) == null
        ? '$label debe ser entero.'
        : null;
  }
}

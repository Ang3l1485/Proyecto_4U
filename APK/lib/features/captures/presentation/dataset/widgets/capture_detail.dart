import 'package:flutter/material.dart';

import '../../../domain/entities/capture.dart';

class CaptureDetail extends StatelessWidget {
  const CaptureDetail({
    super.key,
    required this.capture,
    required this.onEdit,
    required this.onDelete,
  });

  final Capture capture;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final double? heading = capture.metadata.compassHeadingDegrees;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('Detalle', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text('Bloque: ${capture.metadata.block}'),
            Text('Latitud: ${capture.metadata.latitude}'),
            Text('Longitud: ${capture.metadata.longitude}'),
            Text('Recolector: ${capture.metadata.author}'),
            Text('Fecha: ${capture.metadata.timestamp.toLocal()}'),
            Text('Estado: ${capture.metadata.status.name}'),
            Text(
              heading == null
                  ? 'Brújula: no disponible'
                  : 'Brújula: ${capture.metadata.compassDirection} '
                        '(${heading.toStringAsFixed(1)}°)',
            ),
            if (capture.wasQualityOverride)
              const Text('Calidad: guardado forzado registrado'),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: <Widget>[
                FilledButton.icon(
                  onPressed: onEdit,
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('Editar'),
                ),
                OutlinedButton.icon(
                  onPressed: onDelete,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('Eliminar'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

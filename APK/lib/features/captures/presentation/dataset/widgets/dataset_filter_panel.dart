import 'package:flutter/material.dart';

class DatasetFilterPanel extends StatelessWidget {
  const DatasetFilterPanel({
    super.key,
    required this.blockController,
    required this.fromDate,
    required this.toDate,
    required this.onBlockChanged,
    required this.onSelectFromDate,
    required this.onSelectToDate,
    required this.onClear,
  });

  final TextEditingController blockController;
  final DateTime? fromDate;
  final DateTime? toDate;
  final ValueChanged<String> onBlockChanged;
  final VoidCallback onSelectFromDate;
  final VoidCallback onSelectToDate;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: <Widget>[
            TextField(
              controller: blockController,
              decoration: const InputDecoration(
                labelText: 'Filtrar por bloque',
                border: OutlineInputBorder(),
              ),
              onChanged: onBlockChanged,
            ),
            const SizedBox(height: 10),
            Row(
              children: <Widget>[
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onSelectFromDate,
                    icon: const Icon(Icons.date_range),
                    label: Text(_formatDate(fromDate, 'Desde')),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onSelectToDate,
                    icon: const Icon(Icons.event_available),
                    label: Text(_formatDate(toDate, 'Hasta')),
                  ),
                ),
                IconButton(
                  onPressed: onClear,
                  tooltip: 'Limpiar filtros',
                  icon: const Icon(Icons.filter_alt_off),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _formatDate(DateTime? date, String fallback) {
    return date == null ? fallback : '${date.day}/${date.month}/${date.year}';
  }
}

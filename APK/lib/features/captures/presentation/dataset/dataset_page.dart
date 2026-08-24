import 'package:flutter/material.dart';

import '../../domain/entities/capture.dart';
import '../../domain/use_cases/filter_captures.dart';
import '../../domain/use_cases/update_capture_metadata.dart';
import 'dataset_controller.dart';
import 'dataset_state.dart';
import 'widgets/capture_detail.dart';
import 'widgets/capture_editor.dart';
import 'widgets/capture_grid.dart';
import 'widgets/dataset_filter_panel.dart';

class DatasetPage extends StatefulWidget {
  const DatasetPage({super.key, required this.controller});

  final DatasetController controller;

  @override
  State<DatasetPage> createState() => _DatasetPageState();
}

class _DatasetPageState extends State<DatasetPage> {
  final TextEditingController _blockFilterController = TextEditingController();
  DateTime? _fromDate;
  DateTime? _toDate;
  bool _isEditing = false;

  @override
  void initState() {
    super.initState();
    widget.controller.loadCaptures();
  }

  @override
  void dispose() {
    _blockFilterController.dispose();
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (BuildContext context, Widget? child) {
        final DatasetState state = widget.controller.state;
        return RefreshIndicator(
          onRefresh: widget.controller.loadCaptures,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: <Widget>[
              DatasetFilterPanel(
                blockController: _blockFilterController,
                fromDate: _fromDate,
                toDate: _toDate,
                onBlockChanged: (_) => _applyFilter(),
                onSelectFromDate: () => _selectDate(isFromDate: true),
                onSelectToDate: () => _selectDate(isFromDate: false),
                onClear: _clearFilters,
              ),
              if (state.message.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text(state.message),
                ),
              if (state.isLoading)
                const Center(child: CircularProgressIndicator())
              else ...<Widget>[
                if (state.selectedCaptureIds.isNotEmpty)
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.icon(
                      onPressed: state.isMutating ? null : _deleteSelected,
                      icon: const Icon(Icons.delete_outline),
                      label: Text(
                        'Eliminar ${state.selectedCaptureIds.length} seleccionada(s)',
                      ),
                    ),
                  ),
                CaptureGrid(
                  captures: state.filteredCaptures,
                  imagesById: state.imageBytesById,
                  selectedCaptureIds: state.selectedCaptureIds,
                  onOpen: (Capture capture) {
                    setState(() => _isEditing = false);
                    widget.controller.selectCapture(capture);
                  },
                  onToggleSelection: widget.controller.toggleCaptureSelection,
                ),
                if (state.selectedCapture != null) ...<Widget>[
                  const SizedBox(height: 12),
                  if (_isEditing)
                    CaptureEditor(
                      key: ValueKey<String>(state.selectedCapture!.id),
                      capture: state.selectedCapture!,
                      isSaving: state.isMutating,
                      onSave: _saveEdits,
                      onCancel: () => setState(() => _isEditing = false),
                    )
                  else
                    CaptureDetail(
                      capture: state.selectedCapture!,
                      onEdit: () => setState(() => _isEditing = true),
                      onDelete: () => _deleteCapture(state.selectedCapture!),
                    ),
                ],
              ],
            ],
          ),
        );
      },
    );
  }

  void _applyFilter() {
    widget.controller.applyFilter(
      CaptureFilter(
        blockQuery: _blockFilterController.text,
        fromDate: _fromDate,
        toDate: _toDate,
      ),
    );
  }

  Future<void> _selectDate({required bool isFromDate}) async {
    final DateTime initialDate =
        (isFromDate ? _fromDate : _toDate) ?? DateTime.now();
    final DateTime? selected = await showDatePicker(
      context: context,
      initialDate: initialDate,
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (selected == null) {
      return;
    }
    if (!mounted) {
      return;
    }
    setState(() {
      if (isFromDate) {
        _fromDate = selected;
      } else {
        _toDate = selected;
      }
    });
    _applyFilter();
  }

  void _clearFilters() {
    setState(() {
      _blockFilterController.clear();
      _fromDate = null;
      _toDate = null;
    });
    _applyFilter();
  }

  Future<void> _saveEdits(CaptureMetadataChanges changes) async {
    final bool updated = await widget.controller.updateSelectedCapture(changes);
    if (updated && mounted) {
      setState(() => _isEditing = false);
    }
  }

  Future<void> _deleteSelected() async {
    if (await _confirmDeletion('¿Eliminar todas las capturas seleccionadas?')) {
      await widget.controller.deleteSelectedCaptures();
    }
  }

  Future<void> _deleteCapture(Capture capture) async {
    if (await _confirmDeletion('¿Eliminar esta captura y sus metadatos?')) {
      await widget.controller.deleteCapture(capture.id);
      if (mounted) {
        setState(() => _isEditing = false);
      }
    }
  }

  Future<bool> _confirmDeletion(String message) async {
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: const Text('Confirmar eliminación'),
            content: Text(message),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: const Text('Cancelar'),
              ),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: const Text('Eliminar'),
              ),
            ],
          ),
        ) ??
        false;
  }
}

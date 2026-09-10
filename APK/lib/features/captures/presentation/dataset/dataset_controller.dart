import 'package:flutter/foundation.dart';

import '../../domain/entities/capture.dart';
import '../../domain/repositories/capture_repository.dart';
import '../../domain/use_cases/delete_captures.dart';
import '../../domain/use_cases/filter_captures.dart';
import '../../domain/use_cases/list_captures.dart';
import '../../domain/use_cases/update_capture_metadata.dart';
import 'dataset_state.dart';

class DatasetController extends ChangeNotifier {
  DatasetController({
    required CaptureRepository repository,
    required ListCaptures listCaptures,
    required FilterCaptures filterCaptures,
    required UpdateCaptureMetadata updateCaptureMetadata,
    required DeleteCaptures deleteCaptures,
  }) : _repository = repository,
       _listCaptures = listCaptures,
       _filterCaptures = filterCaptures,
       _updateCaptureMetadata = updateCaptureMetadata,
       _deleteCaptures = deleteCaptures;

  final CaptureRepository _repository;
  final ListCaptures _listCaptures;
  final FilterCaptures _filterCaptures;
  final UpdateCaptureMetadata _updateCaptureMetadata;
  final DeleteCaptures _deleteCaptures;

  DatasetState _state = const DatasetState();
  CaptureFilter _activeFilter = const CaptureFilter();

  DatasetState get state => _state;
  CaptureFilter get activeFilter => _activeFilter;

  Future<Uint8List> readCaptureImage(String captureId) {
    return _repository.readCaptureImage(captureId);
  }

  Future<void> loadCaptures() async {
    if (_state.isLoading) {
      return;
    }
    _setState(_copyState(isLoading: true, message: 'Cargando capturas…'));
    try {
      final List<Capture> captures = await _listCaptures.listCaptures();
      final List<Capture> filtered = _filterCaptures.filterCaptures(
        captures,
        _activeFilter,
      );
      _setState(
        DatasetState(
          captures: captures,
          filteredCaptures: filtered,
          selectedCaptureIds: _state.selectedCaptureIds
              .where(
                (String id) => captures.any((Capture item) => item.id == id),
              )
              .toSet(),
          selectedCapture: _captureWithId(captures, _state.selectedCapture?.id),
          message: captures.isEmpty
              ? 'No hay capturas guardadas.'
              : '${captures.length} captura(s) cargada(s).',
        ),
      );
    } catch (error) {
      _setState(
        _copyState(
          isLoading: false,
          message: 'No fue posible cargar el dataset: $error',
        ),
      );
    }
  }

  void applyFilter(CaptureFilter filter) {
    _activeFilter = filter;
    _setState(
      _copyState(
        filteredCaptures: _filterCaptures.filterCaptures(
          _state.captures,
          filter,
        ),
      ),
    );
  }

  void selectCapture(Capture capture) {
    _setState(_copyState(selectedCapture: capture));
  }

  void toggleCaptureSelection(String captureId) {
    final Set<String> selectedIds = Set<String>.from(_state.selectedCaptureIds);
    if (!selectedIds.add(captureId)) {
      selectedIds.remove(captureId);
    }
    _setState(_copyState(selectedCaptureIds: selectedIds));
  }

  Future<bool> updateSelectedCapture(CaptureMetadataChanges changes) async {
    final Capture? selectedCapture = _state.selectedCapture;
    if (selectedCapture == null || _state.isMutating) {
      return false;
    }
    _setState(_copyState(isMutating: true, message: 'Actualizando captura…'));
    try {
      final Capture updated = await _updateCaptureMetadata
          .updateCaptureMetadata(selectedCapture, changes);
      final List<Capture> captures = _state.captures
          .map((Capture capture) {
            return capture.id == updated.id ? updated : capture;
          })
          .toList(growable: false);
      _setState(
        _copyState(
          captures: captures,
          filteredCaptures: _filterCaptures.filterCaptures(
            captures,
            _activeFilter,
          ),
          selectedCapture: updated,
          isMutating: false,
          message: 'Metadatos actualizados sin alterar rumbo ni fecha.',
        ),
      );
      return true;
    } catch (error) {
      _setState(
        _copyState(
          isMutating: false,
          message: 'No fue posible actualizar la captura: $error',
        ),
      );
      return false;
    }
  }

  Future<void> deleteSelectedCaptures() async {
    final Set<String> selectedIds = _state.selectedCaptureIds;
    if (selectedIds.isEmpty || _state.isMutating) {
      return;
    }
    await _deleteCaptureIds(selectedIds);
  }

  Future<void> deleteCapture(String captureId) {
    return _deleteCaptureIds(<String>{captureId});
  }

  Future<void> _deleteCaptureIds(Set<String> captureIds) async {
    _setState(_copyState(isMutating: true, message: 'Eliminando capturas…'));
    try {
      await _deleteCaptures.deleteCaptures(captureIds);
      final List<Capture> remaining = _state.captures
          .where((Capture capture) => !captureIds.contains(capture.id))
          .toList(growable: false);
      _setState(
        DatasetState(
          captures: remaining,
          filteredCaptures: _filterCaptures.filterCaptures(
            remaining,
            _activeFilter,
          ),
          message: 'Captura(s) eliminada(s).',
        ),
      );
    } catch (error) {
      _setState(
        _copyState(
          isMutating: false,
          message: 'No fue posible eliminar las capturas: $error',
        ),
      );
    }
  }

  DatasetState _copyState({
    List<Capture>? captures,
    List<Capture>? filteredCaptures,
    Set<String>? selectedCaptureIds,
    Capture? selectedCapture,
    bool? isLoading,
    bool? isMutating,
    String? message,
  }) {
    return DatasetState(
      captures: captures ?? _state.captures,
      filteredCaptures: filteredCaptures ?? _state.filteredCaptures,
      selectedCaptureIds: selectedCaptureIds ?? _state.selectedCaptureIds,
      selectedCapture: selectedCapture ?? _state.selectedCapture,
      isLoading: isLoading ?? _state.isLoading,
      isMutating: isMutating ?? _state.isMutating,
      message: message ?? _state.message,
    );
  }

  Capture? _captureWithId(List<Capture> captures, String? captureId) {
    if (captureId == null) {
      return null;
    }
    for (final Capture capture in captures) {
      if (capture.id == captureId) {
        return capture;
      }
    }
    return null;
  }

  void _setState(DatasetState newState) {
    _state = newState;
    notifyListeners();
  }
}

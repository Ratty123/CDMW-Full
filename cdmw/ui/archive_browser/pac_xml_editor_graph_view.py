"""Accessible pannable/zoomable PAC XML connection graph widget."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QBrush,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.pac_xml_graph import (
    PacXmlConnectionGraph,
    PacXmlGraphEdge,
    PacXmlGraphNode,
)


_NODE_WIDTH = 260.0
_NODE_HEIGHT = 82.0
_NODE_VERTICAL_GAP = 30.0
_LANE_GAP = 120.0
_LANE_PITCH = _NODE_WIDTH + _LANE_GAP
_READABLE_SCALE = 0.85
_MINIMUM_SCALE = 0.2
_MAXIMUM_SCALE = 2.5


class _NodeItem(QGraphicsRectItem):
    def __init__(self, node: PacXmlGraphNode, callback: Callable[[PacXmlGraphNode], None]) -> None:
        super().__init__(QRectF(0, 0, _NODE_WIDTH, _NODE_HEIGHT))
        self.node = node
        self._callback = callback
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(2)
        status_color = (
            QColor("#2f855a")
            if node.status == "resolved"
            else QColor("#b7791f")
            if node.status == "index warming"
            else QColor("#8b5cf6")
            if node.kind in {"sidecar", "submesh"}
            else QColor("#9b2c2c")
        )
        self.setPen(QPen(status_color, 2))
        self.setBrush(QBrush(QColor("#202733")))

        label = QGraphicsSimpleTextItem(self)
        label_font = label.font()
        label_font.setBold(True)
        label.setFont(label_font)
        label.setText(_elided_text(node.label, label_font, _NODE_WIDTH - 18))
        label.setBrush(QBrush(QColor("#f3f4f6")))
        label.setPos(9, 7)
        label.setAcceptedMouseButtons(Qt.NoButton)

        detail_item = QGraphicsSimpleTextItem(self)
        detail = node.path or node.evidence
        detail_item.setText(
            _elided_text(detail, detail_item.font(), _NODE_WIDTH - 18, Qt.ElideMiddle)
        )
        detail_item.setBrush(QBrush(QColor("#aeb8c7")))
        detail_item.setPos(9, 31)
        detail_item.setAcceptedMouseButtons(Qt.NoButton)

        state_item = QGraphicsSimpleTextItem(self)
        state_item.setText(
            _elided_text(
                " | ".join(part for part in (node.kind, node.status, node.confidence) if part),
                state_item.font(),
                _NODE_WIDTH - 18,
            )
        )
        state_item.setBrush(QBrush(QColor("#8390a3")))
        state_item.setPos(9, 55)
        state_item.setAcceptedMouseButtons(Qt.NoButton)
        self.setToolTip(
            "\n".join(
                part
                for part in (
                    node.path or node.label,
                    f"Status: {node.status}",
                    f"Confidence: {node.confidence}",
                    node.evidence,
                )
                if part
            )
        )

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._callback(self.node)
        super().mouseDoubleClickEvent(event)


class _EdgeItem(QGraphicsPathItem):
    """Wide-hit-area edge whose caption is exposed without cluttering the scene."""

    def __init__(self, edge: PacXmlGraphEdge, path: QPainterPath) -> None:
        super().__init__(path)
        self.edge = edge
        self._hovered = False
        self.setZValue(-2)
        self.setFlag(QGraphicsItem.ItemIsSelectable, bool(edge.row_id))
        self.setAcceptHoverEvents(True)
        self.setData(0, edge.row_id)
        self.setData(1, edge.label)
        self.setData(2, edge.evidence)
        self.setToolTip(
            "\n".join(part for part in (edge.label, edge.confidence, edge.evidence) if part)
        )
        self._update_pen()

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        return stroker.createStroke(self.path())

    def hoverEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = True
        self._update_pen()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = False
        self._update_pen()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):  # type: ignore[no-untyped-def]
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._update_pen(selected=bool(value))
        return result

    def _update_pen(self, *, selected: bool | None = None) -> None:
        is_selected = self.isSelected() if selected is None else selected
        if is_selected:
            self.setPen(QPen(QColor("#f6c85f"), 3.2))
        elif self._hovered:
            self.setPen(QPen(QColor("#a8c7fa"), 2.6))
        elif self.edge.row_id:
            self.setPen(QPen(QColor("#7899c4"), 1.8))
        else:
            self.setPen(QPen(QColor("#637083"), 1.6))


class _BundleItem(QGraphicsPathItem):
    """One uncluttered rail shared by a submesh's parameter branches."""

    def __init__(self, source_id: str, path: QPainterPath, tooltip: str) -> None:
        super().__init__(path)
        self.source_id = source_id
        self.setZValue(-3)
        self.setPen(QPen(QColor("#7899c4"), 1.8))
        self.setToolTip(tooltip)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        return stroker.createStroke(self.path())


class _ZoomableGraphView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setObjectName("PacXmlConnectionGraphicsView")
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current_scale = self.transform().m11()
        requested_scale = current_scale * factor
        if requested_scale < _MINIMUM_SCALE and factor < 1:
            event.accept()
            return
        if requested_scale > _MAXIMUM_SCALE and factor > 1:
            event.accept()
            return
        self.scale(factor, factor)
        event.accept()


class PacXmlConnectionGraphView(QWidget):
    parameterRequested = Signal(str)
    entryPreviewRequested = Signal(object)
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlConnectionsTab")
        self._graph = PacXmlConnectionGraph((), ())
        self._nodes_by_id: dict[str, PacXmlGraphNode] = {}
        self._node_items: dict[str, _NodeItem] = {}
        self._edge_items: dict[str, _EdgeItem] = {}
        self._edge_items_by_row_id: dict[str, _EdgeItem] = {}
        self._bundle_items: list[_BundleItem] = []
        self._list_items: dict[str, QTreeWidgetItem] = {}
        self._edge_list_items: dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        header = QHBoxLayout()
        self.status_label = QLabel("Connections have not been resolved yet.")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        self.readable_button = QPushButton("Readable View")
        self.readable_button.setObjectName("PacXmlGraphReadableButton")
        self.readable_button.setToolTip(
            "Restores a legible zoom and centers the material-to-texture connections."
        )
        self.fit_button = QPushButton("Fit Overview")
        self.fit_button.setObjectName("PacXmlGraphFitButton")
        self.fit_button.setToolTip(
            "Shows the whole map as an overview; use Readable View to inspect labels."
        )
        self.refresh_button = QPushButton("Refresh Indexes")
        self.refresh_button.setObjectName("PacXmlGraphRefreshButton")
        self.refresh_button.setToolTip(
            "Reuses existing archive indexes and Asset Family evidence; it never starts a global scan."
        )
        header.addWidget(self.status_label, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        navigation = QHBoxLayout()
        self.navigation_label = QLabel(
            "Drag the canvas to pan, use the mouse wheel to zoom, and hover or select a line for its parameter name."
        )
        self.navigation_label.setObjectName("PacXmlGraphNavigationHint")
        self.navigation_label.setWordWrap(True)
        navigation.addWidget(self.navigation_label, 1)
        navigation.addWidget(self.readable_button)
        navigation.addWidget(self.fit_button)
        layout.addLayout(navigation)

        splitter = QSplitter(Qt.Vertical)
        self.scene = QGraphicsScene(self)
        self.graphics_view = _ZoomableGraphView(self.scene)
        splitter.addWidget(self.graphics_view)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(
            QLabel(
                "Keyboard-accessible connection list (Enter or double-click previews a resolved file):"
            )
        )
        self.list_tree = QTreeWidget()
        self.list_tree.setObjectName("PacXmlConnectionList")
        self.list_tree.setColumnCount(5)
        self.list_tree.setHeaderLabels(["Kind", "File / Node", "Status", "Confidence", "Evidence"])
        self.list_tree.setRootIsDecorated(False)
        self.list_tree.setAlternatingRowColors(True)
        self.list_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_tree.setTextElideMode(Qt.ElideMiddle)
        list_header = self.list_tree.header()
        list_header.setMinimumSectionSize(72)
        for column in (0, 2, 3):
            list_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (1, 4):
            list_header.setSectionResizeMode(column, QHeaderView.Stretch)
        details_layout.addWidget(self.list_tree)
        self.details_label = QLabel("Select a node or labelled parameter edge for details.")
        self.details_label.setObjectName("PacXmlConnectionDetails")
        self.details_label.setWordWrap(True)
        details_layout.addWidget(self.details_label)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.readable_button.clicked.connect(self.reset_readable_view)
        self.fit_button.clicked.connect(self.fit_graph)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        self.scene.selectionChanged.connect(self._scene_selection_changed)
        self.list_tree.currentItemChanged.connect(self._list_selection_changed)
        self.list_tree.itemActivated.connect(
            lambda item, _column: self._preview_list_item(item)
        )

    @property
    def graph(self) -> PacXmlConnectionGraph:
        return self._graph

    def set_graph(self, graph: PacXmlConnectionGraph) -> None:
        self._graph = graph
        self._nodes_by_id = graph.node_by_id()
        self._node_items.clear()
        self._edge_items.clear()
        self._edge_items_by_row_id.clear()
        self._bundle_items.clear()
        self._list_items.clear()
        self._edge_list_items.clear()
        self.scene.clear()
        self.list_tree.clear()
        positions = _layout_node_positions(graph)
        self._populate_nodes(graph, positions)
        self._populate_edges(graph, positions)

        state = "index warming" if graph.index_warming else "current indexes"
        self.status_label.setText(
            f"{graph.texture_path_count} unique XML asset path(s); "
            f"{graph.unresolved_path_count} unresolved using {state}. "
            "The graph is navigation-only."
        )
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.scene.setSceneRect(bounds.adjusted(-40, -40, 40, 40))
        self.reset_readable_view()

    def _populate_nodes(
        self,
        graph: PacXmlConnectionGraph,
        positions: dict[str, QPointF],
    ) -> None:
        for node in graph.nodes:
            node_item = _NodeItem(node, self._preview_node)
            node_item.setPos(positions[node.node_id])
            self.scene.addItem(node_item)
            self._node_items[node.node_id] = node_item
            list_item = QTreeWidgetItem(
                [node.kind, node.label, node.status, node.confidence, node.evidence]
            )
            list_item.setData(0, Qt.UserRole, node.node_id)
            list_item.setToolTip(1, node.path or node.label)
            list_item.setToolTip(4, node.evidence)
            self.list_tree.addTopLevelItem(list_item)
            self._list_items[node.node_id] = list_item

    def _populate_edges(
        self,
        graph: PacXmlConnectionGraph,
        positions: dict[str, QPointF],
    ) -> None:
        edge_paths, bundle_paths = _layout_edge_paths(graph, positions)
        for source_id, bundle_path in bundle_paths:
            source = self._nodes_by_id[source_id]
            bundle = _BundleItem(
                source_id,
                bundle_path,
                f"Parameter connections from {source.label}",
            )
            self.scene.addItem(bundle)
            self._bundle_items.append(bundle)
        for edge in graph.edges:
            path = edge_paths.get(edge.edge_id)
            if path is None:
                continue
            line = _EdgeItem(edge, path)
            self.scene.addItem(line)
            self._edge_items[edge.edge_id] = line
            if not edge.row_id:
                continue
            self._edge_items_by_row_id[edge.row_id] = line
            edge_item = QTreeWidgetItem(
                ["parameter edge", edge.label, "source", edge.confidence, edge.evidence]
            )
            edge_item.setData(0, Qt.UserRole + 1, edge.row_id)
            edge_item.setData(0, Qt.UserRole + 2, edge.target_id)
            edge_item.setToolTip(1, "Select to locate this exact parameter row.")
            edge_item.setToolTip(4, edge.evidence)
            self.list_tree.addTopLevelItem(edge_item)
            self._edge_list_items[edge.row_id] = edge_item

    def fit_graph(self) -> None:
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.graphics_view.fitInView(
                bounds.adjusted(-30, -30, 30, 30),
                Qt.KeepAspectRatio,
            )

    def reset_readable_view(self) -> None:
        self.graphics_view.resetTransform()
        self.graphics_view.scale(_READABLE_SCALE, _READABLE_SCALE)
        focus = _readable_focus_point(self._graph, self._node_items)
        if focus is not None:
            self.graphics_view.centerOn(focus)

    def select_parameter_edge(self, row_id: str) -> None:
        item = self._edge_items_by_row_id.get(row_id)
        if item is None:
            return
        self.scene.clearSelection()
        item.setSelected(True)
        self._center_on_edge_target(item)

    def _center_on_edge_target(self, item: _EdgeItem) -> None:
        target_item = self._node_items.get(item.edge.target_id)
        center = (
            target_item.sceneBoundingRect().center()
            if target_item is not None
            else item.sceneBoundingRect().center()
        )
        self.graphics_view.centerOn(center)

    def _preview_node(self, node: PacXmlGraphNode) -> None:
        if node.resolved_entry is not None:
            self.entryPreviewRequested.emit(node.resolved_entry)

    def _preview_list_item(self, item: QTreeWidgetItem) -> None:
        row_id = str(item.data(0, Qt.UserRole + 1) or "")
        if row_id:
            self.parameterRequested.emit(row_id)
            return
        node = self._nodes_by_id.get(str(item.data(0, Qt.UserRole) or ""))
        if node is not None:
            self._preview_node(node)

    def _scene_selection_changed(self) -> None:
        selected = self.scene.selectedItems()
        if not selected:
            return
        item = selected[0]
        if isinstance(item, _NodeItem):
            self._show_node_details(item.node)
            list_item = self._list_items.get(item.node.node_id)
            if list_item is not None:
                blocker = QSignalBlocker(self.list_tree)
                self.list_tree.setCurrentItem(list_item)
                del blocker
        elif isinstance(item, _EdgeItem):
            row_id = item.edge.row_id
            self.details_label.setText(
                f"Parameter edge: {item.edge.label}\n{item.edge.evidence}"
            )
            if row_id:
                edge_item = self._edge_list_items.get(row_id)
                if edge_item is not None:
                    blocker = QSignalBlocker(self.list_tree)
                    self.list_tree.setCurrentItem(edge_item)
                    del blocker
                self.parameterRequested.emit(row_id)

    def _list_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        row_id = str(current.data(0, Qt.UserRole + 1) or "")
        if row_id:
            self.details_label.setText(
                f"Parameter edge: {current.text(1)}\n{current.text(4)}"
            )
            edge_item = self._edge_items_by_row_id.get(row_id)
            if edge_item is not None and not edge_item.isSelected():
                self.scene.clearSelection()
                edge_item.setSelected(True)
                self._center_on_edge_target(edge_item)
            else:
                self.parameterRequested.emit(row_id)
            return
        node_id = str(current.data(0, Qt.UserRole) or "")
        node = self._nodes_by_id.get(node_id)
        if node is None:
            return
        self._show_node_details(node)
        node_item = self._node_items.get(node_id)
        if node_item is not None and not node_item.isSelected():
            self.scene.clearSelection()
            node_item.setSelected(True)
            self.graphics_view.ensureVisible(node_item, 50, 50)

    def _show_node_details(self, node: PacXmlGraphNode) -> None:
        self.details_label.setText(
            "\n".join(
                part
                for part in (
                    node.path or node.label,
                    f"Status: {node.status}",
                    f"Confidence: {node.confidence}",
                    node.evidence,
                )
                if part
            )
        )


def _elided_text(
    text: str,
    font: QFont,
    width: float,
    mode: Qt.TextElideMode = Qt.ElideRight,
) -> str:
    return QFontMetricsF(font).elidedText(str(text or ""), mode, max(1, int(width)))


def _layout_node_positions(graph: PacXmlConnectionGraph) -> dict[str, QPointF]:
    lanes: dict[int, list[PacXmlGraphNode]] = defaultdict(list)
    for node in graph.nodes:
        lanes[node.lane].append(node)
    if not lanes:
        return {}

    stride = _NODE_HEIGHT + _NODE_VERTICAL_GAP
    content_height = max(
        _NODE_HEIGHT + max(0, len(nodes) - 1) * stride
        for nodes in lanes.values()
        if nodes
    )
    positions: dict[str, QPointF] = {}
    for lane, nodes in lanes.items():
        block_height = _NODE_HEIGHT + max(0, len(nodes) - 1) * stride
        top = (content_height - block_height) / 2
        for index, node in enumerate(nodes):
            positions[node.node_id] = QPointF(
                lane * _LANE_PITCH,
                top + index * stride,
            )

    outgoing_targets: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        outgoing_targets[edge.source_id].append(edge.target_id)

    submeshes = [node for node in lanes.get(2, ()) if node.kind == "submesh"]
    if submeshes:
        desired_centers = []
        for node in submeshes:
            target_centers = [
                positions[target_id].y() + _NODE_HEIGHT / 2
                for target_id in outgoing_targets.get(node.node_id, ())
                if target_id in positions
            ]
            desired_centers.append(
                sum(target_centers) / len(target_centers)
                if target_centers
                else content_height / 2
            )
        packed_centers = _pack_centers(desired_centers, content_height)
        for node, center in zip(submeshes, packed_centers, strict=True):
            old_position = positions[node.node_id]
            positions[node.node_id] = QPointF(
                old_position.x(),
                center - _NODE_HEIGHT / 2,
            )

    nodes_by_id = graph.node_by_id()
    sidecars = lanes.get(1, ())
    if sidecars:
        child_centers = [
            positions[target_id].y() + _NODE_HEIGHT / 2
            for node in sidecars
            for target_id in outgoing_targets.get(node.node_id, ())
            if target_id in positions and nodes_by_id[target_id].lane == 2
        ]
        root_center = (
            sum(child_centers) / len(child_centers)
            if child_centers
            else content_height / 2
        )
        sidecar_centers = _pack_centers([root_center] * len(sidecars), content_height)
        for node, center in zip(sidecars, sidecar_centers, strict=True):
            old_position = positions[node.node_id]
            positions[node.node_id] = QPointF(
                old_position.x(),
                center - _NODE_HEIGHT / 2,
            )

    models = lanes.get(0, ())
    if models:
        root_center = (
            sum(positions[node.node_id].y() + _NODE_HEIGHT / 2 for node in sidecars)
            / len(sidecars)
            if sidecars
            else content_height / 2
        )
        model_centers = _pack_centers([root_center] * len(models), content_height)
        for node, center in zip(models, model_centers, strict=True):
            old_position = positions[node.node_id]
            positions[node.node_id] = QPointF(
                old_position.x(),
                center - _NODE_HEIGHT / 2,
            )
    return positions


def _pack_centers(desired: list[float], content_height: float) -> list[float]:
    if not desired:
        return []
    minimum = _NODE_HEIGHT / 2
    maximum = content_height - _NODE_HEIGHT / 2
    separation = _NODE_HEIGHT + _NODE_VERTICAL_GAP
    centers: list[float] = []
    for value in desired:
        centers.append(max(minimum, value, centers[-1] + separation if centers else minimum))
    if centers[-1] > maximum:
        centers[-1] = maximum
        for index in range(len(centers) - 2, -1, -1):
            centers[index] = min(centers[index], centers[index + 1] - separation)
    if centers[0] < minimum:
        shift = minimum - centers[0]
        centers = [center + shift for center in centers]
    return centers


def _layout_edge_paths(
    graph: PacXmlConnectionGraph,
    positions: dict[str, QPointF],
) -> tuple[dict[str, QPainterPath], list[tuple[str, QPainterPath]]]:
    outgoing: dict[str, list[PacXmlGraphEdge]] = defaultdict(list)
    incoming: dict[str, list[PacXmlGraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        if edge.source_id in positions and edge.target_id in positions:
            outgoing[edge.source_id].append(edge)
            incoming[edge.target_id].append(edge)

    def center_y(node_id: str) -> float:
        return positions[node_id].y() + _NODE_HEIGHT / 2

    for node_id, edges in outgoing.items():
        source_x = positions[node_id].x()
        edges.sort(
            key=lambda edge: (
                0
                if positions[edge.target_id].x() - source_x > _LANE_PITCH * 1.5
                else 1,
                center_y(edge.target_id),
                edge.edge_id,
            )
        )
    for edges in incoming.values():
        edges.sort(key=lambda edge: (center_y(edge.source_id), edge.edge_id))

    outgoing_index = {
        edge.edge_id: (index, len(edges))
        for edges in outgoing.values()
        for index, edge in enumerate(edges)
    }
    incoming_index = {
        edge.edge_id: (index, len(edges))
        for edges in incoming.values()
        for index, edge in enumerate(edges)
    }
    long_edges = [
        edge
        for edge in graph.edges
        if edge.edge_id in outgoing_index
        and positions[edge.target_id].x() - positions[edge.source_id].x()
        > _LANE_PITCH * 1.5
    ]
    long_edge_index = {edge.edge_id: index for index, edge in enumerate(long_edges)}
    candidate_groups: dict[tuple[str, float], list[PacXmlGraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        if (
            edge.edge_id not in outgoing_index
            or edge.edge_id in long_edge_index
            or not edge.row_id
        ):
            continue
        candidate_groups[(edge.source_id, positions[edge.target_id].x())].append(edge)
    bundle_groups = {
        key: edges
        for key, edges in candidate_groups.items()
        if len(edges) > 1
    }
    groups_by_gap: dict[tuple[float, float], list[tuple[str, float]]] = defaultdict(list)
    for source_id, target_x in bundle_groups:
        groups_by_gap[(positions[source_id].x(), target_x)].append((source_id, target_x))

    bundle_rail_by_edge: dict[str, float] = {}
    bundle_paths: list[tuple[str, QPainterPath]] = []
    for (_source_x, target_x), group_keys in groups_by_gap.items():
        group_keys.sort(key=lambda key: (center_y(key[0]), key[0]))
        for group_index, group_key in enumerate(group_keys):
            source_id, _group_target_x = group_key
            source = positions[source_id]
            rail_x = source.x() + _NODE_WIDTH + (
                target_x - source.x() - _NODE_WIDTH
            ) * ((len(group_keys) - group_index) / (len(group_keys) + 1))
            edges = bundle_groups[group_key]
            target_ys = [
                positions[edge.target_id].y()
                + _port_offset(*incoming_index[edge.edge_id])
                for edge in edges
            ]
            source_y = center_y(source_id)
            rail_path = QPainterPath(QPointF(source.x() + _NODE_WIDTH, source_y))
            rail_path.lineTo(rail_x, source_y)
            rail_path.moveTo(rail_x, min(source_y, *target_ys))
            rail_path.lineTo(rail_x, max(source_y, *target_ys))
            bundle_paths.append((source_id, rail_path))
            for edge in edges:
                bundle_rail_by_edge[edge.edge_id] = rail_x
    top = min(position.y() for position in positions.values()) if positions else 0.0

    paths: dict[str, QPainterPath] = {}
    for edge in graph.edges:
        if edge.edge_id not in outgoing_index:
            continue
        source = positions[edge.source_id]
        target = positions[edge.target_id]
        source_port = _port_offset(*outgoing_index[edge.edge_id])
        target_port = _port_offset(*incoming_index[edge.edge_id])
        start = source + QPointF(_NODE_WIDTH, source_port)
        end = target + QPointF(0.0, target_port)
        if edge.edge_id in bundle_rail_by_edge:
            path = QPainterPath(QPointF(bundle_rail_by_edge[edge.edge_id], end.y()))
            path.lineTo(end)
        elif edge.edge_id in long_edge_index:
            path = QPainterPath(start)
            route_index = long_edge_index[edge.edge_id]
            route_spread = min(route_index * 2.0, _LANE_GAP - 56.0)
            bus_y = top - 58.0 - route_index * 12.0
            source_bus_x = start.x() + 28.0 + route_spread
            target_bus_x = end.x() - 28.0 - route_spread
            path.cubicTo(
                QPointF(start.x() + 18.0, start.y()),
                QPointF(source_bus_x, bus_y + 24.0),
                QPointF(source_bus_x, bus_y),
            )
            path.lineTo(target_bus_x, bus_y)
            path.cubicTo(
                QPointF(target_bus_x, bus_y + 24.0),
                QPointF(end.x() - 18.0, end.y()),
                end,
            )
        else:
            path = QPainterPath(start)
            control_distance = max(34.0, (end.x() - start.x()) * 0.48)
            path.cubicTo(
                QPointF(start.x() + control_distance, start.y()),
                QPointF(end.x() - control_distance, end.y()),
                end,
            )
        paths[edge.edge_id] = path
    return paths, bundle_paths


def _port_offset(index: int, count: int) -> float:
    if count <= 1:
        return _NODE_HEIGHT / 2
    margin = 10.0
    return margin + index * ((_NODE_HEIGHT - margin * 2) / (count - 1))


def _readable_focus_point(
    graph: PacXmlConnectionGraph,
    node_items: dict[str, _NodeItem],
) -> QPointF | None:
    preferred = [node for node in graph.nodes if node.kind == "submesh"]
    fallback = [node for node in graph.nodes if node.kind == "sidecar"]
    candidates = preferred or fallback or list(graph.nodes[:1])
    if not candidates:
        return None
    centers = [node_items[node.node_id].sceneBoundingRect().center() for node in candidates]
    center_y = centers[0].y()
    center_x = centers[0].x()
    texture_items = [
        node_items[node.node_id]
        for node in graph.nodes
        if node.kind == "texture"
    ]
    if texture_items:
        texture_x = texture_items[0].sceneBoundingRect().center().x()
        center_x = (center_x + texture_x) / 2
    return QPointF(center_x, center_y)


__all__ = ["PacXmlConnectionGraphView"]
